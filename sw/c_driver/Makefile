CXX = g++
CXXFLAGS = -O3 -Wall -std=c++11 `pkg-config --cflags opencv4`
LDFLAGS = -lopencv_core -lopencv_videoio -lopencv_imgproc -lopencv_highgui

# Fallback to older opencv if opencv4 pkg-config isn't found
ifeq ($(shell pkg-config --exists opencv4 && echo yes),)
	CXXFLAGS = -O3 -Wall -std=c++11 `pkg-config --cflags opencv`
	LDFLAGS = -lopencv_core -lopencv_videoio -lopencv_imgproc -lopencv_highgui
endif

TARGET = retina_driver
SRCS = main.cpp

all: $(TARGET)

$(TARGET): $(SRCS)
	$(CXX) $(CXXFLAGS) -o $(TARGET) $(SRCS) $(LDFLAGS)

clean:
	rm -f $(TARGET)
