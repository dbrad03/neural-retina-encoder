use crossbeam_channel::bounded;
use minifb::{Key, Scale, ScaleMode, Window, WindowOptions};
use std::net::UdpSocket;
use std::thread;
use std::time::{Duration, Instant};

const GRID_SIZE: usize = 128;
const WIN_WIDTH: usize = GRID_SIZE * 2;
const WIN_HEIGHT: usize = GRID_SIZE * 2;
const MIN_WINDOW_SIZE: usize = 256;

enum VisualizerEvent {
    Spike(usize),
    SpikeBatch(Vec<usize>),
    StimulusFrame(Vec<u8>),
}

fn main() {
    let (tx, rx) = bounded::<VisualizerEvent>(1024);

    // --- NETWORK THREAD ---
    thread::spawn(move || {
        let socket = UdpSocket::bind("0.0.0.0:8080").expect("Could not bind UDP socket");
        println!("Listening for retina UDP packets on 0.0.0.0:8080");
        let mut buf = [0u8; 16385]; // Large enough for a header + full frame
        let mut spike_count: u64 = 0;
        let mut spike_packet_count: u64 = 0;
        let mut image_count: u64 = 0;
        let mut last_report = Instant::now();

        loop {
            if let Ok((amt, src)) = socket.recv_from(&mut buf) {
                match buf[0] {
                    1 => { // Legacy spike packet: [1, addr_hi, addr_lo]
                        if amt >= 3 {
                            let addr = ((buf[1] as usize) << 8) | (buf[2] as usize);
                            spike_count += 1;
                            spike_packet_count += 1;
                            let _ = tx.try_send(VisualizerEvent::Spike(addr));
                        }
                    }
                    2 => { // Stimulus frame: [2, 128*128 luma bytes]
                        if amt >= 1 + (GRID_SIZE * GRID_SIZE) {
                            let frame = buf[1..1 + (GRID_SIZE * GRID_SIZE)].to_vec();
                            image_count += 1;
                            let _ = tx.try_send(VisualizerEvent::StimulusFrame(frame));
                        }
                    }
                    3 => { // Spike batch: [3, count_hi, count_lo, addr_hi, addr_lo, ...]
                        if amt >= 3 {
                            let declared = ((buf[1] as usize) << 8) | (buf[2] as usize);
                            let available = (amt - 3) / 2;
                            let count = declared.min(available);
                            let mut spikes = Vec::with_capacity(count);
                            for i in 0..count {
                                let off = 3 + i * 2;
                                spikes.push(((buf[off] as usize) << 8) | (buf[off + 1] as usize));
                            }
                            spike_count += count as u64;
                            spike_packet_count += 1;
                            let _ = tx.try_send(VisualizerEvent::SpikeBatch(spikes));
                        }
                    }
                    _ => {}
                }

                if last_report.elapsed() >= Duration::from_secs(1) {
                    println!(
                        "UDP from {src}: {image_count} image packets, {spike_count} spikes in {spike_packet_count} spike packets"
                    );
                    image_count = 0;
                    spike_count = 0;
                    spike_packet_count = 0;
                    last_report = Instant::now();
                }
            }
        }
    });

    // --- UI THREAD ---
    let mut logical_buffer: Vec<u32> = vec![0; WIN_WIDTH * WIN_HEIGHT];
    let mut window_buffer: Vec<u32> = vec![0; WIN_WIDTH * WIN_HEIGHT];
    let mut persistence_buffer: Vec<u32> = vec![0; GRID_SIZE * GRID_SIZE];
    let mut stimulus_buffer: Vec<u8> = vec![0; GRID_SIZE * GRID_SIZE];
    let mut instant_spikes: Vec<bool> = vec![false; GRID_SIZE * GRID_SIZE];
    
    let mut window = Window::new(
        "Science Eye Quadrant Visualizer",
        WIN_WIDTH,
        WIN_HEIGHT,
        WindowOptions {
            resize: true,
            scale: Scale::X4,
            scale_mode: ScaleMode::Stretch,
            ..WindowOptions::default()
        },
    ).unwrap();

    window.set_target_fps(60);

    while window.is_open() && !window.is_key_down(Key::Escape) {
        
        // 1. Decay the persistence buffer (Bottom-Left quadrant)
        for pixel in persistence_buffer.iter_mut() {
            let g = ((*pixel >> 8) & 0xFF).saturating_sub(10);
            *pixel = g << 8;
        }

        // 2. Process new events from the Network
        instant_spikes.fill(false);
        for event in rx.try_iter() {
            match event {
                VisualizerEvent::Spike(addr) => {
                    if addr < GRID_SIZE * GRID_SIZE {
                        instant_spikes[addr] = true;
                        persistence_buffer[addr] = 0x00FF00; // Bright Green
                    }
                }
                VisualizerEvent::SpikeBatch(spikes) => {
                    for addr in spikes {
                        if addr < GRID_SIZE * GRID_SIZE {
                            instant_spikes[addr] = true;
                            persistence_buffer[addr] = 0x00FF00; // Bright Green
                        }
                    }
                }
                VisualizerEvent::StimulusFrame(frame) => {
                    stimulus_buffer = frame;
                }
            }
        }

        // 3. Compose the Quadrants
        for y in 0..WIN_HEIGHT {
            for x in 0..WIN_WIDTH {
                let quad_x = x / GRID_SIZE;
                let quad_y = y / GRID_SIZE;
                let local_x = x % GRID_SIZE;
                let local_y = y % GRID_SIZE;
                let idx = local_y * GRID_SIZE + local_x;
                let out_idx = y * WIN_WIDTH + x;

                // Draw a faint 16x16 grid to make the retinal array visible
                let is_grid_line = local_x % 16 == 0 || local_y % 16 == 0;
                let grid_color = 0x111111; // Very faint gray
                
                // Draw a biological eye/retina map outline
                let dx = local_x as f32 - 64.0;
                let dy = local_y as f32 - 64.0;
                let dist = (dx * dx + dy * dy).sqrt();
                // Outer Retina Edge
                let is_retina_edge = dist > 59.0 && dist < 61.0;
                // Inner Fovea/Pupil Edge
                let is_fovea_edge = dist > 14.0 && dist < 16.0;
                // Horizontal optic nerve line
                let is_optic_nerve = (dy > -1.0 && dy < 1.0) && local_x > 64;
                
                let is_eye_drawing = is_retina_edge || is_fovea_edge || is_optic_nerve;
                let eye_color = 0x555555; // Brighter gray for the eye outline

                match (quad_x, quad_y) {
                    (0, 0) => { // TOP-LEFT: Stimulus (Greyscale)
                        let val = stimulus_buffer[idx];
                        logical_buffer[out_idx] = (val as u32) << 16 | (val as u32) << 8 | (val as u32);
                    }
                    (1, 0) => { // TOP-RIGHT: Instant Spikes (White)
                        if instant_spikes[idx] {
                            logical_buffer[out_idx] = 0xFFFFFF;
                        } else if is_eye_drawing {
                            logical_buffer[out_idx] = eye_color;
                        } else if is_grid_line {
                            logical_buffer[out_idx] = grid_color;
                        } else {
                            logical_buffer[out_idx] = 0;
                        }
                    }
                    (0, 1) => { // BOTTOM-LEFT: Persistence (Green)
                        let p = persistence_buffer[idx];
                        if p > 0 {
                            logical_buffer[out_idx] = p;
                        } else if is_eye_drawing {
                            logical_buffer[out_idx] = eye_color;
                        } else if is_grid_line {
                            logical_buffer[out_idx] = grid_color;
                        } else {
                            logical_buffer[out_idx] = 0;
                        }
                    }
                    (1, 1) => { // BOTTOM-RIGHT: Composite View (Stimulus + Instant Spikes)
                        let val = stimulus_buffer[idx] / 2;
                        let base_bg = val as u32; // Dim blue background for stimulus
                        
                        if instant_spikes[idx] {
                            logical_buffer[out_idx] = 0xFFFFFF; // White flash
                        } else if is_eye_drawing {
                            logical_buffer[out_idx] = eye_color | base_bg;
                        } else if is_grid_line {
                            logical_buffer[out_idx] = grid_color | base_bg;
                        } else {
                            logical_buffer[out_idx] = base_bg;
                        }
                    }
                    _ => {}
                }
            }
        }

        let (window_w, window_h) = window.get_size();
        let render_size = window_w.min(window_h).max(MIN_WINDOW_SIZE);
        if window_buffer.len() != render_size * render_size {
            window_buffer.resize(render_size * render_size, 0);
        }

        for y in 0..render_size {
            let sy = y * WIN_HEIGHT / render_size;
            for x in 0..render_size {
                let sx = x * WIN_WIDTH / render_size;
                window_buffer[y * render_size + x] = logical_buffer[sy * WIN_WIDTH + sx];
            }
        }

        window.update_with_buffer(&window_buffer, render_size, render_size).unwrap();
    }
}
