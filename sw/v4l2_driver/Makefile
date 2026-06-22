# Pure V4L2 retina driver - no OpenCV, links only libc (+ libm).
# Build:  make          (frame_done by polling)
#         make UIO=1     (frame_done by /dev/uio0; needs uio_retina.dtbo)
CC = gcc
CFLAGS = -O3 -Wall -Wextra -std=c11
LDFLAGS = -lm

ifeq ($(UIO),1)
	CFLAGS += -DUSE_UIO
endif

TARGET = retina_v4l2
SRCS = retina_v4l2.c

all: $(TARGET)

$(TARGET): $(SRCS)
	$(CC) $(CFLAGS) -o $(TARGET) $(SRCS) $(LDFLAGS)

clean:
	rm -f $(TARGET)
