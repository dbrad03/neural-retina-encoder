#include <iostream>
#include <vector>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <opencv2/opencv.hpp>
#include <cstring>

// FPGA Addresses
#define RETINA_BASE 0x40000000
#define FIFO_BASE   0x43C00000

// Offsets
#define RETINA_PIXEL_RAM 0x00000
#define RETINA_CONTROL   0x10000

#define FIFO_RDFO 0x1C
#define FIFO_RDFD 0x20

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <host_ip>\n";
        return 1;
    }
    const char* host_ip = argv[1];

    // Setup UDP Socket
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in servaddr;
    memset(&servaddr, 0, sizeof(servaddr));
    servaddr.sin_family = AF_INET;
    servaddr.sin_port = htons(8080);
    servaddr.sin_addr.s_addr = inet_addr(host_ip);

    // Setup /dev/mem
    int mem_fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (mem_fd < 0) {
        std::cerr << "Failed to open /dev/mem. Are you root?\n";
        return 1;
    }

    void* retina_map = mmap(NULL, 0x20000, PROT_READ | PROT_WRITE, MAP_SHARED, mem_fd, RETINA_BASE);
    void* fifo_map   = mmap(NULL, 0x10000, PROT_READ | PROT_WRITE, MAP_SHARED, mem_fd, FIFO_BASE);

    if (retina_map == MAP_FAILED || fifo_map == MAP_FAILED) {
        std::cerr << "mmap failed.\n";
        return 1;
    }

    volatile uint32_t* retina_ram = (volatile uint32_t*)((uint8_t*)retina_map + RETINA_PIXEL_RAM);
    volatile uint32_t* retina_ctrl = (volatile uint32_t*)((uint8_t*)retina_map + RETINA_CONTROL);
    volatile uint32_t* fifo_rdfo = (volatile uint32_t*)((uint8_t*)fifo_map + FIFO_RDFO);
    volatile uint32_t* fifo_rdfd = (volatile uint32_t*)((uint8_t*)fifo_map + FIFO_RDFD);

    // Setup UIO for Interrupts
    int uio_fd = open("/dev/uio0", O_RDWR);
    if (uio_fd < 0) {
        std::cerr << "Failed to open /dev/uio0. Ensure device tree is configured for generic-uio.\n";
        return 1;
    }

    // Setup Camera
    cv::VideoCapture cap(0);
    if (!cap.isOpened()) {
        std::cerr << "Failed to open /dev/video0.\n";
        return 1;
    }
    
    // Request a smaller resolution from the webcam to keep framerate high
    cap.set(cv::CAP_PROP_FRAME_WIDTH, 320);
    cap.set(cv::CAP_PROP_FRAME_HEIGHT, 240);
    cap.set(cv::CAP_PROP_FPS, 30);

    cv::Mat frame, gray, resized;
    std::vector<uint8_t> img_packet(1 + 128*128);
    img_packet[0] = 2; // Type 2 = Image

    std::cout << "Starting live retina feed using UIO Interrupts. Streaming to " << host_ip << ":8080...\n";
    std::cout << "Press Ctrl+C to stop.\n";

    while (true) {
        cap >> frame;
        if (frame.empty()) {
            std::cerr << "Camera frame empty, skipping...\n";
            continue;
        }

        // Convert to grayscale and resize to match FPGA grid (128x128)
        cv::cvtColor(frame, gray, cv::COLOR_BGR2GRAY);
        cv::resize(gray, resized, cv::Size(128, 128));

        // 1. Write pixels to FPGA and pack UDP image buffer
        for (int y = 0; y < 128; y++) {
            for (int x = 0; x < 128; x++) {
                uint8_t val = resized.at<uint8_t>(y, x);
                img_packet[1 + y*128 + x] = val;
                
                // Convert 0-255 grayscale to Q8.10 scale used by our Izhikevich model.
                // Formula: (val / 10.0) * 1024.0 = val * 102.4
                uint32_t q8_10 = (uint32_t)(val * 102.4f);
                retina_ram[y*128 + x] = q8_10;
            }
        }

        // 2. Send Stimulus Image over UDP to Visualizer
        sendto(sock, img_packet.data(), img_packet.size(), 0, (const struct sockaddr *)&servaddr, sizeof(servaddr));

        // 3. Unmask/Enable the UIO interrupt in Linux
        uint32_t irq_on = 1;
        write(uio_fd, &irq_on, sizeof(irq_on));

        // 4. Trigger FPGA Hardware Frame Evaluation
        *retina_ctrl = 0x03; // Bit 0: Start, Bit 1: Clear Done

        // 5. Block on UIO interrupt (0% CPU utilization while waiting!)
        uint32_t irq_count;
        int ret = read(uio_fd, &irq_count, sizeof(irq_count));
        if (ret < 0) {
            std::cerr << "UIO read failed.\n";
            break;
        }

        // 6. Read Spikes from AXI FIFO
        uint32_t len_bytes = *fifo_rdfo;
        uint32_t num_words = len_bytes / 4;

        for (uint32_t i = 0; i < num_words; i++) {
            uint32_t data = *fifo_rdfd;
            uint16_t addr = data & 0xFFFF; // Spike address is in lower 16 bits
            
            // Pack Spike UDP Packet: Type 1
            uint8_t spike_pkt[3];
            spike_pkt[0] = 1;
            spike_pkt[1] = (addr >> 8) & 0xFF; // High byte
            spike_pkt[2] = addr & 0xFF;        // Low byte

            sendto(sock, spike_pkt, 3, 0, (const struct sockaddr *)&servaddr, sizeof(servaddr));
        }
    }

    close(uio_fd);
    close(sock);
    return 0;
}
