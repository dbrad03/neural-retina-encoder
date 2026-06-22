/*
 * retina_v4l2.c - Phase 5 live driver for the Science Eye retina.
 *
 * Pure V4L2 (no OpenCV) so it ports cleanly to a lean PetaLinux rootfs later.
 * Front-end: grab YUYV frames from /dev/video0, take the luma (Y) plane,
 * downsample to 128x128, convert to Q8.10, push into the PL pixel RAM.
 * Back-end: trigger a frame, wait for frame_done (poll by default, or UIO if
 * built with -DUSE_UIO), drain the spike FIFO, stream stimulus + spikes via UDP.
 *
 * Reuses the /dev/mem mmap, Q8.10 mapping, and UDP framing from
 * sw/c_driver/main.cpp. Key fix vs main.cpp: the spike FIFO is drained by
 * RDFO occupancy (already in WORDS) -- main.cpp divided RDFO by 4 as if bytes.
 *
 * Build:  make            (polling)
 *         make UIO=1      (block on /dev/uio0; needs uio_retina.dtbo loaded)
 * Run:    sudo ./retina_v4l2 <host_ip> [/dev/videoN]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <sys/time.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <linux/videodev2.h>

/* ---- FPGA address map (matches main.cpp / system.hwh) ------------------- */
#define RETINA_BASE 0x40000000UL
#define RETINA_SPAN 0x20000UL
#define FIFO_BASE   0x43C00000UL
#define FIFO_SPAN   0x10000UL

#define OFF_PIXEL_RAM 0x00000
#define OFF_CONTROL   0x10000

#define CTRL_START      0x1
#define CTRL_CLEAR_DONE 0x2
#define CTRL_CLEAR_OVF  0x4
#define STAT_DONE       0x2
#define STAT_OVERFLOW   0x4

#define FIFO_RDFR 0x18
#define FIFO_RDFO 0x1C   /* receive occupancy in WORDS */
#define FIFO_RDFD 0x20   /* receive data */
#define FIFO_RLR  0x24   /* receive length in BYTES (valid once a TLAST packet is present) */

#define GRID 128
#define NUM_NEURONS (GRID * GRID)

#define CAP_W 320
#define CAP_H 240
#define N_BUFS 4

#define UDP_PORT 8080
#define PKT_IMAGE 2
#define PKT_SPIKE 1

static volatile uint32_t *retina_ram, *retina_ctrl;
static volatile uint32_t *fifo;

struct buffer { void *start; size_t length; };

static int xioctl(int fd, unsigned long req, void *arg) {
    int r;
    do { r = ioctl(fd, req, arg); } while (r == -1 && errno == EINTR);
    return r;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <host_ip> [/dev/videoN]\n", argv[0]);
        return 1;
    }
    const char *host_ip = argv[1];
    const char *vdev = (argc > 2) ? argv[2] : "/dev/video0";

    /* ---- UDP socket ---- */
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in srv;
    memset(&srv, 0, sizeof(srv));
    srv.sin_family = AF_INET;
    srv.sin_port = htons(UDP_PORT);
    srv.sin_addr.s_addr = inet_addr(host_ip);

    /* ---- /dev/mem mappings ---- */
    int mem_fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (mem_fd < 0) { perror("open /dev/mem (need root)"); return 1; }
    void *rmap = mmap(NULL, RETINA_SPAN, PROT_READ | PROT_WRITE, MAP_SHARED, mem_fd, RETINA_BASE);
    void *fmap = mmap(NULL, FIFO_SPAN,   PROT_READ | PROT_WRITE, MAP_SHARED, mem_fd, FIFO_BASE);
    if (rmap == MAP_FAILED || fmap == MAP_FAILED) { perror("mmap"); return 1; }
    retina_ram  = (volatile uint32_t *)((uint8_t *)rmap + OFF_PIXEL_RAM);
    retina_ctrl = (volatile uint32_t *)((uint8_t *)rmap + OFF_CONTROL);
    fifo        = (volatile uint32_t *)fmap;

#ifdef USE_UIO
    int uio_fd = open("/dev/uio0", O_RDWR);
    if (uio_fd < 0) { perror("open /dev/uio0 (load uio_retina.dtbo, or rebuild without UIO=1)"); return 1; }
#endif

    /* ---- V4L2 open + format ---- */
    int cam = open(vdev, O_RDWR);
    if (cam < 0) { perror("open camera"); return 1; }

    struct v4l2_format fmt;
    memset(&fmt, 0, sizeof(fmt));
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    fmt.fmt.pix.width = CAP_W;
    fmt.fmt.pix.height = CAP_H;
    fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_YUYV;
    fmt.fmt.pix.field = V4L2_FIELD_NONE;
    if (xioctl(cam, VIDIOC_S_FMT, &fmt) < 0) { perror("VIDIOC_S_FMT"); return 1; }
    if (fmt.fmt.pix.pixelformat != V4L2_PIX_FMT_YUYV) {
        fprintf(stderr, "Camera did not accept YUYV; got 0x%x. Adjust front-end.\n",
                fmt.fmt.pix.pixelformat);
        return 1;
    }
    unsigned cw = fmt.fmt.pix.width, ch = fmt.fmt.pix.height;

    /* ---- request + mmap capture buffers ---- */
    struct v4l2_requestbuffers req;
    memset(&req, 0, sizeof(req));
    req.count = N_BUFS;
    req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    req.memory = V4L2_MEMORY_MMAP;
    if (xioctl(cam, VIDIOC_REQBUFS, &req) < 0) { perror("VIDIOC_REQBUFS"); return 1; }

    struct buffer bufs[N_BUFS];
    for (unsigned i = 0; i < req.count; i++) {
        struct v4l2_buffer b;
        memset(&b, 0, sizeof(b));
        b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        b.memory = V4L2_MEMORY_MMAP;
        b.index = i;
        if (xioctl(cam, VIDIOC_QUERYBUF, &b) < 0) { perror("VIDIOC_QUERYBUF"); return 1; }
        bufs[i].length = b.length;
        bufs[i].start = mmap(NULL, b.length, PROT_READ | PROT_WRITE, MAP_SHARED, cam, b.m.offset);
        if (bufs[i].start == MAP_FAILED) { perror("mmap buf"); return 1; }
        if (xioctl(cam, VIDIOC_QBUF, &b) < 0) { perror("VIDIOC_QBUF"); return 1; }
    }

    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(cam, VIDIOC_STREAMON, &type) < 0) { perror("VIDIOC_STREAMON"); return 1; }

    uint8_t img_packet[1 + NUM_NEURONS];
    img_packet[0] = PKT_IMAGE;

    printf("Live retina feed from %s (%ux%u YUYV) -> %s:%d. Ctrl+C to stop.\n",
           vdev, cw, ch, host_ip, UDP_PORT);

    for (;;) {
        struct v4l2_buffer b;
        memset(&b, 0, sizeof(b));
        b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        b.memory = V4L2_MEMORY_MMAP;
        if (xioctl(cam, VIDIOC_DQBUF, &b) < 0) { perror("VIDIOC_DQBUF"); break; }

        const uint8_t *yuyv = (const uint8_t *)bufs[b.index].start;

        /* Downsample luma (every other byte = Y) to 128x128, nearest neighbor. */
        for (int gy = 0; gy < GRID; gy++) {
            int sy = gy * ch / GRID;
            for (int gx = 0; gx < GRID; gx++) {
                int sx = gx * cw / GRID;
                uint8_t y = yuyv[(sy * cw + sx) * 2];   /* Y plane */
                img_packet[1 + gy * GRID + gx] = y;
                retina_ram[gy * GRID + gx] = (uint32_t)(y * 102.4f); /* Q8.10 */
            }
        }

        sendto(sock, img_packet, sizeof(img_packet), 0, (struct sockaddr *)&srv, sizeof(srv));

        /* Trigger one frame evaluation. */
        retina_ctrl[0] = CTRL_CLEAR_DONE | CTRL_CLEAR_OVF;
#ifdef USE_UIO
        uint32_t on = 1; write(uio_fd, &on, sizeof(on));   /* unmask */
        retina_ctrl[0] = CTRL_START | CTRL_CLEAR_DONE;
        uint32_t cnt; if (read(uio_fd, &cnt, sizeof(cnt)) < 0) { perror("uio read"); break; }
#else
        retina_ctrl[0] = CTRL_START | CTRL_CLEAR_DONE;
        while (!(retina_ctrl[0] & STAT_DONE)) { /* spin */ }
#endif

        /* Drain the spike FIFO. One TLAST packet per frame: if RDFO>0, read RLR
         * (byte length, also consumes the length-FIFO entry) and pop RLR/4 words.
         * Never read RLR when RDFO==0 -> it returns SLVERR (bus abort). */
        uint32_t occ = fifo[FIFO_RDFO / 4];
        if (occ > 0) {
            uint32_t nwords = fifo[FIFO_RLR / 4] / 4;
            for (uint32_t i = 0; i < nwords; i++) {
                uint32_t data = fifo[FIFO_RDFD / 4];
                uint16_t a = data & 0xFFFF;
                uint8_t spk[3] = { PKT_SPIKE, (uint8_t)((a >> 8) & 0xFF), (uint8_t)(a & 0xFF) };
                sendto(sock, spk, 3, 0, (struct sockaddr *)&srv, sizeof(srv));
            }
        }

        if (xioctl(cam, VIDIOC_QBUF, &b) < 0) { perror("VIDIOC_QBUF requeue"); break; }
    }

    xioctl(cam, VIDIOC_STREAMOFF, &type);
    close(cam);
#ifdef USE_UIO
    close(uio_fd);
#endif
    close(sock);
    return 0;
}
