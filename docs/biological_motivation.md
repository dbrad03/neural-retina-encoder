# Biological Motivation

The Science Eye uses visual prosthetics to restore sight. Simply stimulating the optic nerve with flat electrical pulses creates visual noise. This system encodes images into realistic, biologically-accurate spike trains before the signal reaches the optic nerve, taking advantage of the Izhikevich model.

## Midget vs Parasol Cells

The human retina contains a variety of ganglion cells. We model two primary ones:
1. **Midget Cells (Fovea):**
   - High spatial resolution.
   - Characterized by slow, steady firing under continuous stimulus.
   - Used for resolving sharp details in the center of our vision.
   - Modeled via Izhikevich parameters: `a = 0.02, b = 0.2, c = -65.0, d = 8.0`.

2. **Parasol Cells (Periphery):**
   - Low spatial resolution but high temporal resolution.
   - Characterized by fast, bursting spikes that quickly adapt/decay.
   - Used for detecting quick movement in our peripheral vision.
   - Modeled via Izhikevich parameters: `a = 0.1, b = 0.2, c = -65.0, d = 2.0`.

## Foveated Mapping
Our 128x128 array implements a spatial map matching this behavior:
- The inner radii map entirely to **Midget cells**.
- The outer rings map to **Parasol cells**.

This heterogeneity provides significant power and data-bandwidth advantages while rendering a closer-to-nature sensory experience for the end-user.
