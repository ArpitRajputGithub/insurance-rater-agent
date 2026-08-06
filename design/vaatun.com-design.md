---
version: alpha
name: Vaatun Purple Tech
description: A light, editorial landing-page system with strong purple branding, large rounded cards, and confident insurance-tech messaging.
colors:
  primary: "#5B3D91"
  primary-60: "#8B5CF6"
  primary-80: "#6D4AA8"
  secondary: "#2E284C"
  tertiary: "#E2E8F0"
  neutral: "#FFFFFF"
  surface: "#F8FAFC"
  on-surface: "#2E284C"
  muted: "#CAD5E2"
  border: "#E2E8F0"
  success: "#7CCB7A"
  error: "#D64545"
typography:
  headline-display:
    fontFamily: Satoshi
    fontSize: 56px
    fontWeight: 400
    lineHeight: 1.05
    letterSpacing: -0.03em
  headline-lg:
    fontFamily: Satoshi
    fontSize: 48px
    fontWeight: 400
    lineHeight: 1.08
    letterSpacing: -0.03em
  headline-md:
    fontFamily: Satoshi
    fontSize: 32px
    fontWeight: 400
    lineHeight: 38px
    letterSpacing: 0px
  headline-sm:
    fontFamily: Satoshi
    fontSize: 27px
    fontWeight: 400
    lineHeight: 36px
    letterSpacing: -0.04em
  title-md:
    fontFamily: Satoshi
    fontSize: 23px
    fontWeight: 400
    lineHeight: 36px
    letterSpacing: -0.04em
  title-sm:
    fontFamily: Satoshi
    fontSize: 19px
    fontWeight: 400
    lineHeight: 23px
    letterSpacing: 0.03em
  body-lg:
    fontFamily: Satoshi
    fontSize: 18px
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: 0px
  body-md:
    fontFamily: Satoshi
    fontSize: 16px
    fontWeight: 400
    lineHeight: 24px
    letterSpacing: 0px
  body-sm:
    fontFamily: Satoshi
    fontSize: 14px
    fontWeight: 400
    lineHeight: 20px
    letterSpacing: 0px
  label-lg:
    fontFamily: Satoshi
    fontSize: 18px
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: 0px
  label-md:
    fontFamily: Satoshi
    fontSize: 16px
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: 0px
  label-sm:
    fontFamily: Satoshi
    fontSize: 14px
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: 0px
  nav-md:
    fontFamily: Satoshi
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: 0px
  link-sm:
    fontFamily: Satoshi
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: 0px
rounded:
  none: 0px
  sm: 8px
  md: 10px
  lg: 16px
  xl: 24px
  full: 9999px
spacing:
  xs: 8px
  sm: 16px
  md: 28px
  lg: 40px
  xl: 72px
  gutter: 24px
  margin: 32px
components:
  button-primary:
    backgroundColor: "{colors.neutral}"
    textColor: "{colors.secondary}"
    typography: "{typography.label-lg}"
    rounded: "{rounded.md}"
    padding: "12px 27px"
    height: "53px"
  button-primary-hover:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.secondary}"
    rounded: "{rounded.md}"
  button-secondary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.neutral}"
    typography: "{typography.label-lg}"
    rounded: "{rounded.md}"
    padding: "12px 27px"
    height: "53px"
  button-secondary-hover:
    backgroundColor: "{colors.primary-80}"
    textColor: "{colors.neutral}"
    rounded: "{rounded.md}"
  button-link:
    backgroundColor: "transparent"
    textColor: "{colors.primary}"
    typography: "{typography.body-md}"
    rounded: "{rounded.none}"
    padding: "0px"
  card:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.neutral}"
    rounded: "{rounded.lg}"
    padding: "20px"
  input:
    backgroundColor: "{colors.neutral}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.md}"
    padding: "12px 16px"
    height: "53px"
  chip:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.full}"
    padding: "6px 12px"
---

# Vaatun Purple Tech

## Overview
Vaatun feels like a confident, modern B2B landing page for an insurance-tech audience. The tone is professional but not stiff: large headlines, generous whitespace, and bright violet accents create a forward-looking, optimistic feel. The layout is spacious and editorial, with a strong preference for clear hierarchy and card-based storytelling.

## Colors
- **Primary (#5B3D91):** The core brand purple used for primary actions, key accents, and branded UI surfaces. It reads as premium, tech-forward, and trustworthy.
- **Primary Accent (#8B5CF6):** A brighter violet highlight that adds energy to gradients, badges, and emphasis moments.
- **Secondary (#2E284C):** A deep ink-like plum used for body text, dark cards, and high-contrast areas. It anchors the otherwise airy palette.
- **Tertiary (#E2E8F0):** A soft cool border tone used for dividers, outlines, and subtle structural lines.
- **Neutral (#FFFFFF):** The main canvas color for the page and most buttons, keeping the interface clean and open.
- **Surface (#F8FAFC):** A pale background layer for chips, utility surfaces, and subtle separation without introducing heavy contrast.
- **On-surface (#2E284C):** The default readable text color on light backgrounds.
- **Muted (#CAD5E2):** A restrained border and shadow-adjacent tone for outlined controls.
- **Border (#E2E8F0):** The standard rule color for cards, sections, and input outlines.
- **Success (#7CCB7A):** A supporting positive state color, used sparingly if needed.
- **Error (#D64545):** Reserved for validation and failure states; should remain visually distinct from the purple brand system.

## Typography
Satoshi is the sole visible voice of the system, giving the site a clean, contemporary, slightly geometric feel. Headings are light in weight rather than bold, which makes the large sizes feel elegant and editorial instead of heavy. Body text stays comfortably readable at 16px with a 24px line height, while labels and navigation rely on medium weight for clarity.

The hierarchy is built through size and spacing more than weight changes. Headline styles favor tight negative tracking on larger display levels, while the smallest title level uses slightly expanded spacing for compact UI labeling. Uppercase treatment is not a dominant convention in the screenshot; the typography leans into sentence case and straightforward readability.

## Layout
The page uses a centered, wide desktop container with a strong grid and clear vertical segmentation. Large content blocks are separated by thin borders rather than heavy panels, which keeps the composition airy while still structured. Spacing follows a restrained rhythm based on 8px increments, with larger jumps at 28px, 40px, and 72px for section breaks and major composition changes.

Cards and hero panels use generous internal padding, typically around 20px to 28px, with the main CTA cluster and headline area given more breathing room. The interface feels fixed-max-width on desktop rather than fluidly expansive, with content aligned to a clear column system and comfortable outer gutters.

## Elevation & Depth
Depth is created with minimal shadows and stronger tonal contrast instead of layered elevation. Primary buttons use a visible drop-shadow to create a tactile, lifted effect, while cards themselves are mostly flat and defined by borders and background color differences. Dark purple cards create visual emphasis through saturation and contrast rather than blur or heavy shadow.

Because the system is mostly flat, hierarchy should come from spacing, border color, and the shift between white, pale surface tones, and deep plum panels. Use shadow sparingly and only for interactive affordance or emphasis.

## Shapes
The shape language is rounded but controlled. Interactive controls use a 10px radius, giving buttons and inputs a friendly, modern edge without becoming overly soft. Larger cards use a 16px radius, and hero modules may feel slightly more generous, reinforcing the premium, polished tone.

Overall, the system balances approachable curves with a structured grid. Circles are used for icon containers and small action elements, while most other components remain clean and rectangular.

## Components
Buttons are a defining part of the UI. The primary button style is light with a white background, dark text, a subtle border, and a shadow that makes it feel raised; it works well for secondary conversion actions like “Get Started Today.” The secondary button style is filled with primary purple and white text, making it the strongest CTA treatment for actions like “Request a Call Back.” Button padding should stay around 12px 27px with a minimum height near 53px for strong desktop presence. Hover states should deepen the purple or soften the white surface slightly while preserving the same radius and clear label contrast.

Cards are large, rounded, and content-rich. Dark cards use the secondary plum background with white text, while brighter cards can use primary purple or gradient-like tonal variation to differentiate content modules. Keep card padding around 20px and preserve the 16px radius. Cards should rely on internal hierarchy, not decorative framing.

Inputs should match the button geometry: white background, subtle border, 10px radius, and comfortable 12px 16px padding. Focus states should be visible but restrained, ideally using the primary purple rather than a heavy glow. Validation should use the error color sparingly.

Chips and small utility badges should be compact and pill-shaped with a full radius. Use the surface color and purple text for low-emphasis filters, tags, or status markers. Links should remain simple and text-only, using primary purple without underlines unless needed for accessibility.

Navigation items are understated and editorial. They should sit on the white header bar with medium spacing, simple text styling, and small caret indicators where needed. Icon buttons and circular action affordances should remain minimal, using white or pale circles against dark surfaces for contrast.

## Do's and Don'ts
- Do keep the interface spacious and editorial, with clear section separation and generous line height.
- Do use Satoshi consistently for all headings, body copy, navigation, and labels.
- Do reserve primary purple for key actions, highlights, and brand moments.
- Do prefer borders and tonal contrast over heavy shadows for most surfaces.
- Don’t introduce sharp corners or overly square controls that break the soft modern feel.
- Don’t overuse gradients; keep them as accent moments inside hero and feature cards.
- Don’t switch to a bold, condensed, or highly decorative typeface.
- Don’t crowd cards or buttons; preserve the roomy desktop rhythm visible in the design.