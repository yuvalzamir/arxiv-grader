# Scholarly Obsidian Design System

### 1. Overview & Creative North Star
**Creative North Star: The Digital Curator**
Scholarly Obsidian is a design system built for the intersection of rigorous academic research and high-end editorial aesthetics. It moves away from the "SaaS dashboard" look in favor of a "Literary Journal" feel. The system utilizes intentional asymmetry—such as vertical text specimens and offset grids—to create a sense of intellectual depth. It prioritizes white space and high-contrast typography to ensure that complex data feels breathable and curated rather than overwhelming.

### 2. Colors
The palette is rooted in deep ink tones (`primary: #041627`) and architectural greys, accented by a scientific teal (`tertiary`).

*   **The "No-Line" Rule:** Sectioning is strictly prohibited from using 1px solid borders. Separation must be achieved through background shifts (e.g., moving from `surface` to `surface-container-low`) or subtle tonal transitions.
*   **Surface Hierarchy & Nesting:** Use `surface-container-low` for large background sections and `surface-container-lowest` for cards or focus areas that need to "pop" against the background.
*   **The "Glass & Gradient" Rule:** Floating action bars and footers must use `backdrop-blur` (8px to 12px) with a semi-transparent `surface` background to maintain context of the content beneath.
*   **Signature Textures:** Incorporate ultra-low opacity oversized iconography (3% opacity) as background watermarks to break up solid color blocks.

### 3. Typography
The system uses a sophisticated pairing of **Newsreader** (Serif) for narrative weight and **Inter** (Sans) for functional clarity.

*   **Display & Headline (Newsreader):** Uses a fluid scale. Large headings (e.g., 3.5rem) should use negative tracking (-0.02em) and occasional italics for emphasis (e.g., "Taste *Profile*").
*   **Body (Inter):** Rendered at 1.125rem for long-form reading and 0.875rem for functional descriptions.
*   **Labels (Inter):** All-caps, tracked out (0.15em to 0.5em), and rendered in small sizes (10px-11px) to act as architectural "metadata" rather than primary reading content.

**Extracted Scale:** 
- Display: 3.5rem (56px) / Leading 1.1
- Section Heading: 1.25rem (20px)
- Body: 1.125rem (18px)
- Small Body: 0.875rem (14px)
- Functional Label: 10px / 11px

### 4. Elevation & Depth
Depth is created through "Tonal Stacking" rather than elevation shadows where possible.

*   **The Layering Principle:** A `surface-container-lowest` card on a `surface` background creates a natural lift without needing heavy shadows.
*   **Ambient Shadows:** When shadows are required (e.g., `shadow-lg` for primary containers), they must be extra-diffused. Use a large blur radius (32px - 48px) with a very low opacity (4%) primary-colored tint to simulate natural light.
*   **The "Ghost Border":** For interactive elements like textareas, use `outline-variant` at 15% opacity to provide a structural hint without a "boxed-in" feeling.

### 5. Components
*   **Buttons:** Primary buttons are sharp-edged (radius: 0.125rem to full pill for CTAs) with high-contrast `on-primary` text. CTA buttons use a `primary/20` shadow.
*   **Bulk Input:** Text areas use `surface-container-low` backgrounds and mono-spaced fonts for technical precision.
*   **Upload Zones:** Use dashed `outline-variant` borders to signify "emptiness" or a drop zone, changing to a solid tonal shift on hover.
*   **Sidebar:** Fixed, narrow, using `surface-container` equivalent colors to create a structural anchor that doesn't compete with the main canvas.

### 6. Do's and Don'ts
*   **Do:** Use vertical text rotations for decorative metadata on the edges of the screen.
*   **Do:** Use italics within headlines to highlight key concepts.
*   **Don't:** Use standard 8px or 12px border radii; keep corners either very sharp (2px) or fully pill-shaped.
*   **Don't:** Use solid black (#000). Always use the ink-based `primary` or `on-surface` for text to maintain a softer, printed-page feel.
*   **Do:** Maintain a spacing of at least 32px (spacing: 3) between major editorial blocks to allow the typography to breathe.