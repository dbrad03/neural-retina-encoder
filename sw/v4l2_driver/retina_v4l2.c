#define _POSIX_C_SOURCE 200809L

/*
 * retina_v4l2.c - Phase 5 live driver for the Science Eye retina.
 *
 * Pure V4L2 (no OpenCV) so it ports cleanly to a lean PetaLinux rootfs later.
 * Front-end: grab YUYV frames from /dev/video0, take the luma (Y) plane,
 * downsample to 128x128, convert to Q8.10, push into the PL pixel RAM.
 * Back-end: trigger a frame, wait for frame_done (poll by default, or UIO if
 * built with -DUSE_UIO), drain the spike FIFO, stream stimulus + spikes via UDP.
 *
 * UDP protocol:
 *   packet 2: [2, 128*128 luma bytes]
 *   packet 3: [3, count_hi, count_lo, addr_hi, addr_lo, ...]
 * The Rust visualizer still accepts legacy packet 1 single-spike datagrams.
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
#include <sys/select.h>
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

#define N_BUFS 4

#define UDP_PORT 8080
#define PKT_STIMULUS_FRAME 2
#define PKT_SPIKE_BATCH 3
#define SPIKE_BATCH_MAX 512

static volatile uint32_t *retina_ram, *retina_ctrl;
static volatile uint32_t *fifo;

struct buffer { void *start; size_t length; };

static int xioctl(int fd, unsigned long req, void *arg) {
    int r;
    do { r = ioctl(fd, req, arg); } while (r == -1 && errno == EINTR);
    return r;
}

/* Monotonic nanosecond clock for the BENCH=1 per-stage latency breakdown. */
static uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static void send_udp_packet(int sock, const struct sockaddr_in *dst,
                            const uint8_t *data, size_t len,
                            const char *packet_name) {
    ssize_t sent = sendto(sock, data, len, 0,
                          (const struct sockaddr *)dst, sizeof(*dst));
    if (sent < 0) {
        fprintf(stderr, "retina_v4l2: sendto %s failed: %s\n",
                packet_name, strerror(errno));
    } else if ((size_t)sent != len) {
        fprintf(stderr, "retina_v4l2: short sendto %s: %zd/%zu bytes\n",
                packet_name, sent, len);
    }
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IOLBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);

    if (argc < 2) {
        fprintf(stderr, "Usage: %s <host_ip> [/dev/videoN]\n", argv[0]);
        return 1;
    }
    const char *host_ip = argv[1];
    const char *vdev = (argc > 2) ? argv[2] : "/dev/video0";

    fprintf(stderr, "retina_v4l2: target=%s:%d camera=%s\n", host_ip, UDP_PORT, vdev);

    /* ---- UDP socket ---- */
    fprintf(stderr, "retina_v4l2: opening UDP socket...\n");
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) { perror("socket"); return 1; }
    struct sockaddr_in srv;
    memset(&srv, 0, sizeof(srv));
    srv.sin_family = AF_INET;
    srv.sin_port = htons(UDP_PORT);
    srv.sin_addr.s_addr = inet_addr(host_ip);

    /* ---- /dev/mem mappings ---- */
    fprintf(stderr, "retina_v4l2: mapping FPGA registers...\n");
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
    fprintf(stderr, "retina_v4l2: opening camera...\n");
    int cam = open(vdev, O_RDWR);
    if (cam < 0) { perror("open camera"); return 1; }

    /* Capture mode is env-configurable so bandwidth can be dialed down WITHOUT a
     * recompile. The ci_hdrc isoc scheduler can't reserve YUYV 320x240@30
     * (~37 Mbps) -> VIDIOC_STREAMON returns ENOMEM. Default to a low-bandwidth
     * mode that fits; we downsample to 128x128 anyway. Override with
     * CAM_W / CAM_H / CAM_FPS env vars. */
    unsigned want_w   = getenv("CAM_W")   ? (unsigned)atoi(getenv("CAM_W"))   : 160;
    unsigned want_h   = getenv("CAM_H")   ? (unsigned)atoi(getenv("CAM_H"))   : 120;
    unsigned want_fps = getenv("CAM_FPS") ? (unsigned)atoi(getenv("CAM_FPS")) : 15;

    fprintf(stderr, "retina_v4l2: requesting %ux%u YUYV @ %u fps...\n", want_w, want_h, want_fps);
    struct v4l2_format fmt;
    memset(&fmt, 0, sizeof(fmt));
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    fmt.fmt.pix.width = want_w;
    fmt.fmt.pix.height = want_h;
    fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_YUYV;
    fmt.fmt.pix.field = V4L2_FIELD_NONE;
    if (xioctl(cam, VIDIOC_S_FMT, &fmt) < 0) { perror("VIDIOC_S_FMT"); return 1; }
    if (fmt.fmt.pix.pixelformat != V4L2_PIX_FMT_YUYV) {
        fprintf(stderr, "Camera did not accept YUYV; got 0x%x. Adjust front-end.\n",
                fmt.fmt.pix.pixelformat);
        return 1;
    }
    unsigned cw = fmt.fmt.pix.width, ch = fmt.fmt.pix.height;
    unsigned stride = fmt.fmt.pix.bytesperline ? fmt.fmt.pix.bytesperline : cw * 2;
    fprintf(stderr, "retina_v4l2: granted %ux%u stride=%u sizeimage=%u\n",
            cw, ch, stride, fmt.fmt.pix.sizeimage);

    /* Lower the frame rate too (further cuts isoc bandwidth; best-effort). */
    struct v4l2_streamparm parm;
    memset(&parm, 0, sizeof(parm));
    parm.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    parm.parm.capture.timeperframe.numerator = 1;
    parm.parm.capture.timeperframe.denominator = want_fps;
    if (xioctl(cam, VIDIOC_S_PARM, &parm) == 0)
        fprintf(stderr, "retina_v4l2: frame interval %u/%u s\n",
                parm.parm.capture.timeperframe.numerator,
                parm.parm.capture.timeperframe.denominator);

    /* Force CONSTANT frame rate. Many UVC cams (incl. the C270) silently HALVE
     * the delivered rate in low light: with V4L2_CID_EXPOSURE_AUTO_PRIORITY=1 the
     * firmware may lengthen exposure past the frame interval (dynamic framerate),
     * so a granted 1/30 s still arrives at ~15 fps. Setting it to 0 keeps the
     * requested rate. Best-effort; the scene still needs enough light to actually
     * hold the higher rate (otherwise images just get darker, not slower). */
    struct v4l2_control xctl;
    memset(&xctl, 0, sizeof(xctl));
    xctl.id = V4L2_CID_EXPOSURE_AUTO_PRIORITY;
    xctl.value = 0;
    if (xioctl(cam, VIDIOC_S_CTRL, &xctl) == 0)
        fprintf(stderr, "retina_v4l2: exposure_auto_priority=0 (constant fps)\n");
    else
        fprintf(stderr, "retina_v4l2: exposure_auto_priority not set (%s); "
                "fps may halve in low light\n", strerror(errno));

    /* ---- request + mmap capture buffers ---- */
    fprintf(stderr, "retina_v4l2: requesting capture buffers...\n");
    struct v4l2_requestbuffers req;
    memset(&req, 0, sizeof(req));
    req.count = N_BUFS;
    req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    req.memory = V4L2_MEMORY_MMAP;
    if (xioctl(cam, VIDIOC_REQBUFS, &req) < 0) { perror("VIDIOC_REQBUFS"); return 1; }

    struct buffer bufs[N_BUFS];
    for (unsigned i = 0; i < req.count; i++) {
        fprintf(stderr, "retina_v4l2: mapping camera buffer %u...\n", i);
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
    fprintf(stderr, "retina_v4l2: starting camera stream...\n");
    if (xioctl(cam, VIDIOC_STREAMON, &type) < 0) { perror("VIDIOC_STREAMON"); return 1; }

    uint8_t img_packet[1 + NUM_NEURONS];
    img_packet[0] = PKT_STIMULUS_FRAME;

    printf("Live retina feed from %s (%ux%u YUYV) -> %s:%d. Ctrl+C to stop.\n",
           vdev, cw, ch, host_ip, UDP_PORT);

    /* BENCH=1 prints a per-stage latency breakdown every BENCH_EVERY frames.
     * Timestamps are captured unconditionally (clock_gettime is ~tens of ns,
     * negligible at video frame rates); accounting/printing is gated on bench. */
    const int bench = getenv("BENCH") != NULL;
    const unsigned BENCH_EVERY = 30;
    uint64_t acc_cap = 0, acc_write = 0, acc_stim = 0, acc_frame = 0, acc_drain = 0;
    unsigned bench_n = 0;
    uint64_t bench_win = now_ns();
    if (bench) fprintf(stderr, "retina_v4l2: BENCH on (breakdown every %u frames)\n", BENCH_EVERY);

    /* Run N Izhikevich timesteps per captured image. The camera caps the input
     * rate (~30 fps on a C270), but the neuron state integrates continuously, so
     * triggering the engine N times per frame emits N spike updates per image ->
     * the output update rate is decoupled from (and N x) the camera rate. */
    unsigned steps_per_frame = getenv("STEPS_PER_FRAME")
                             ? (unsigned)atoi(getenv("STEPS_PER_FRAME")) : 1;
    if (steps_per_frame < 1) steps_per_frame = 1;
    fprintf(stderr, "retina_v4l2: %u engine timestep(s) per camera frame\n", steps_per_frame);

    for (;;) {
        uint64_t t_top = now_ns();
        /* Wait up to 2s for a frame so a stalled stream reports a timeout
         * instead of blocking forever in DQBUF. */
        fd_set fds; FD_ZERO(&fds); FD_SET(cam, &fds);
        struct timeval tv = { .tv_sec = 2, .tv_usec = 0 };
        int sr = select(cam + 1, &fds, NULL, NULL, &tv);
        if (sr == 0) { fprintf(stderr, "retina_v4l2: no frame (2s timeout)\n"); continue; }
        if (sr < 0)  { if (errno == EINTR) continue; perror("select"); break; }

        struct v4l2_buffer b;
        memset(&b, 0, sizeof(b));
        b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        b.memory = V4L2_MEMORY_MMAP;
        if (xioctl(cam, VIDIOC_DQBUF, &b) < 0) { perror("VIDIOC_DQBUF"); break; }

        const uint8_t *yuyv = (const uint8_t *)bufs[b.index].start;
        uint64_t t_cap = now_ns();   /* select + DQBUF (camera-bound at low fps) */

        /* Downsample luma (every other byte = Y) to 128x128, nearest neighbor. */
        for (int gy = 0; gy < GRID; gy++) {
            int sy = gy * ch / GRID;
            for (int gx = 0; gx < GRID; gx++) {
                int sx = gx * cw / GRID;
                uint8_t y = yuyv[sy * stride + sx * 2];   /* Y plane, stride-aware */
                img_packet[1 + gy * GRID + gx] = y;
                retina_ram[gy * GRID + gx] = ((uint32_t)y * 512) / 5; /* Q8.10 (exact integer scaling equivalent to y * 102.4) */
            }
        }
        uint64_t t_write = now_ns();   /* downsample + 16384 AXI-Lite pixel writes */

        send_udp_packet(sock, &srv, img_packet, sizeof(img_packet), "stimulus frame");
        uint64_t t_stim = now_ns();    /* stimulus-frame UDP send */

        /* Run steps_per_frame Izhikevich timesteps on this captured image. The
         * neuron state persists in PL BRAM between triggers, so each step
         * advances the dynamics and emits its own spike packet. */
        uint64_t step_frame_ns = 0, step_drain_ns = 0;
        int io_err = 0;
        for (unsigned step = 0; step < steps_per_frame; step++) {
            uint64_t s0 = now_ns();

            /* Trigger one frame evaluation. */
            retina_ctrl[0] = CTRL_CLEAR_DONE | CTRL_CLEAR_OVF;
#ifdef USE_UIO
            uint32_t on = 1; write(uio_fd, &on, sizeof(on));   /* unmask */
            retina_ctrl[0] = CTRL_START | CTRL_CLEAR_DONE;
            uint32_t cnt; if (read(uio_fd, &cnt, sizeof(cnt)) < 0) { perror("uio read"); io_err = 1; break; }
#else
            retina_ctrl[0] = CTRL_START | CTRL_CLEAR_DONE;
            while (!(retina_ctrl[0] & STAT_DONE)) { /* spin */ }
#endif
            uint64_t s1 = now_ns();
            step_frame_ns += s1 - s0;

            /* The closing TLAST can arrive after frame_done while the internal
             * spike FIFO drains. Wait briefly for axi_fifo_mm_s to commit the
             * packet before reading RLR or starting the next step. */
            uint32_t occ = fifo[FIFO_RDFO / 4];
            struct timespec deadline;
            clock_gettime(CLOCK_MONOTONIC, &deadline);
            deadline.tv_nsec += 250000; /* 250 us: full 16k-word drain is ~164 us at 100 MHz */
            if (deadline.tv_nsec >= 1000000000L) {
                deadline.tv_sec++;
                deadline.tv_nsec -= 1000000000L;
            }
            while (occ == 0) {
                struct timespec now;
                clock_gettime(CLOCK_MONOTONIC, &now);
                if (now.tv_sec > deadline.tv_sec ||
                    (now.tv_sec == deadline.tv_sec && now.tv_nsec >= deadline.tv_nsec)) {
                    break;
                }
                occ = fifo[FIFO_RDFO / 4];
            }

            /* Drain the spike FIFO. One TLAST packet per step: if RDFO>0, read RLR
             * (byte length, also consumes the length-FIFO entry) and pop RLR/4 words.
             * Never read RLR when RDFO==0 -> it returns SLVERR (bus abort). */
            if (occ > 0) {
                uint32_t nwords = fifo[FIFO_RLR / 4] / 4;
                uint8_t spk_batch[1 + 2 + SPIKE_BATCH_MAX * 2];
                uint32_t batch_count = 0;
                spk_batch[0] = PKT_SPIKE_BATCH;

                for (uint32_t i = 0; i < nwords; i++) {
                    uint32_t data = fifo[FIFO_RDFD / 4];
                    uint16_t a = data & 0xFFFF;
                    size_t off = 3 + batch_count * 2;
                    spk_batch[off] = (uint8_t)((a >> 8) & 0xFF);
                    spk_batch[off + 1] = (uint8_t)(a & 0xFF);
                    batch_count++;

                    if (batch_count == SPIKE_BATCH_MAX) {
                        spk_batch[1] = (uint8_t)((batch_count >> 8) & 0xFF);
                        spk_batch[2] = (uint8_t)(batch_count & 0xFF);
                        send_udp_packet(sock, &srv, spk_batch, 3 + batch_count * 2,
                                        "spike batch");
                        batch_count = 0;
                    }
                }

                if (batch_count > 0) {
                    spk_batch[1] = (uint8_t)((batch_count >> 8) & 0xFF);
                    spk_batch[2] = (uint8_t)(batch_count & 0xFF);
                    send_udp_packet(sock, &srv, spk_batch, 3 + batch_count * 2,
                                    "spike batch");
                }
            }
            uint64_t s2 = now_ns();
            step_drain_ns += s2 - s1;
        }
        if (io_err) break;
        /* Bench buckets: total scan / drain time for all steps this camera frame. */
        uint64_t t_frame = t_stim + step_frame_ns;
        uint64_t t_drain = t_frame + step_drain_ns;

        if (bench) {
            acc_cap   += t_cap   - t_top;
            acc_write += t_write - t_cap;
            acc_stim  += t_stim  - t_write;
            acc_frame += t_frame - t_stim;
            acc_drain += t_drain - t_frame;
            if (++bench_n >= BENCH_EVERY) {
                double n = (double)bench_n;
                uint64_t wall = now_ns() - bench_win;
                /* compute = the part NOT waiting on the camera (write+frame+drain) */
                double compute = (acc_write + acc_frame + acc_drain) / n / 1e3;
                double cam_fps = n * 1e9 / (double)wall;
                /* frame/drain are summed over all steps this camera frame, so
                 * their averages already reflect steps_per_frame. */
                printf("[bench] %u frames x %u steps | capture %.0f | pixel_write %.0f | "
                       "stim_udp %.0f | frame %.0f | drain %.0f us "
                       "(all avg) | compute(w+f+d) %.0f us | %.1f cam fps -> %.1f spike updates/s\n",
                       bench_n, steps_per_frame,
                       acc_cap / n / 1e3, acc_write / n / 1e3, acc_stim / n / 1e3,
                       acc_frame / n / 1e3, acc_drain / n / 1e3,
                       compute, cam_fps, cam_fps * steps_per_frame);
                acc_cap = acc_write = acc_stim = acc_frame = acc_drain = 0;
                bench_n = 0;
                bench_win = now_ns();
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
