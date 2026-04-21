# H2OMeta UI Scheme v1.1

**Status:** Approved visual and interaction scheme  
**Date:** 2026-04-21  
**Scope:** Workspace shell, navigation, page structure, and key detail-page interaction patterns

> This document is the canonical UI scheme for the current frontend direction.
> If lower-level notes or ad hoc mockups conflict with this document, this document wins.

## 1. Design Intent

H2OMeta is a **workspace-style scientific workbench**, not:

- a tab-heavy desktop utility
- an IDE
- a file-browser-first app
- a dashboard wall

The intended product feel is:

- **Notion-like** in restraint and page structure
- **Linear-like** in workflow density and object clarity
- **scientific** in how runs, results, and server state are surfaced

The core goal is to make complex execution and result inspection feel stable, understandable, and low-noise.

## 2. Core Layout

### 2.1 Shell

The primary shell consists of:

- **Left sidebar**
- **Top tabs bar**
- **Right content area**
- **Bottom terminal dock** (secondary, debug/reassurance surface)

### 2.2 Frame baseline

Figma baseline frame:

- **Desktop:** `1440 x 960`

### 2.3 Main split

- **Sidebar width:** `228px`
- **Right content area:** fill remaining width

### 2.4 Vertical structure

- **Tabs bar height:** `44px`
- **Content inner padding:** `24px`
- **Section gap:** `20px`

## 3. Visual Principles

### 3.1 Hierarchy by spacing, not decoration

Prefer:

- spacing
- typography
- subtle surfaces
- thin dividers

Avoid:

- heavy cards everywhere
- thick outlines
- strong shadows
- saturated status blocks

### 3.2 Surface contrast

Primary surface tones:

- App background: `#FBFBFA`
- Sidebar background: `#F7F7F5`
- Content background: `#FFFFFF`
- Divider: `#E5E7EB`
- Primary text: `#0F172A`
- Secondary text: `#64748B`

Use the very small contrast difference between `#FBFBFA` and `#FFFFFF` to create the “Notion-like” layered feel.

### 3.3 Density model

- Sidebar: medium density
- List pages: medium density
- Detail pages: lower density, more breathing room

## 4. Typography

- **Page title:** `24 / Semibold`
- **Section title:** `18 / Semibold`
- **Card / block title:** `15 / Medium`
- **Primary body:** `14 / Regular`
- **Secondary body:** `13 / Regular`
- **Meta / caption / breadcrumb:** `11–12 / Medium`

The product should feel precise and readable, not oversized or decorative.

## 5. Sidebar Scheme

### 5.1 Top: Connection block

Connection belongs at the top of the sidebar because it functions as a system-level state indicator.

Contents:

- icon: `Link2`
- title: `Connection`
- subtitle:
  - connected: `user@host:port`
  - disconnected: `未连接远端服务器`
- overflow menu on the right when connected

Behavior:

- disconnected: clicking the connection block may open the connect dialog
- connected: block itself stays quiet; overflow handles disconnect/manage actions

Visual rule:

- integrated into sidebar background
- not a loud standalone card
- hover should be restrained

### 5.2 Middle: Primary navigation

Ordered items:

- Home
- Servers
- Projects
- Runs
- Results

Each item uses:

- icon + text
- active background
- subtle hover background

### 5.3 Bottom: Settings

Settings is anchored to the bottom of the sidebar.

This reinforces its role as global configuration rather than content navigation.

## 6. Tabs Bar Scheme

### 6.1 Role of tabs

Tabs are retained to preserve a **browser-like sense of return** and context continuity.

Tabs are **not** the primary navigation system.  
They are a lightweight “currently open content” layer inside the workspace.

### 6.2 Visual form

- browser-like, lightweight tabs
- active tab uses white surface
- inactive tabs blend into the tabs bar
- closable
- draggable/reorderable

### 6.3 Behavioral principle

Tabs should feel like persistent context, not like the app’s main IA.

That means:

- sidebar remains the authoritative global navigation
- tabs help users return to current work
- tabs should not create route confusion

## 7. Breadcrumb Scheme

Breadcrumbs are required for deeper object detail pages.

They are especially important for:

- Project detail
- Run detail
- Result detail

Examples:

- `Projects / H2O_Project_A`
- `Projects / H2O_Project_A / Runs / RUN-8821`
- `Projects / H2O_Project_A / Results / Taxonomy Report`

Breadcrumb style:

- subtle
- small
- low-contrast
- above page title

List/index pages do not require complex breadcrumbs.

## 8. Terminal Presence

The terminal is more than a debug tool; in this product it also provides a sense of execution “liveness” and reassurance.

### 8.1 Terminal button

Keep the terminal button visible in shell chrome.

### 8.2 Status indication

The terminal button should eventually support a small status indicator:

- disconnected: grey
- connected idle: blue-grey
- running: soft blue pulse / breathing state
- error: red dot
- optional unread output indicator later

For Figma, include a variant that suggests a subtle “breathing” running state.

### 8.3 Terminal dock role

Terminal remains:

- secondary
- collapsible
- supportive

It must not dominate the primary page experience.

## 9. Page Templates

### 9.1 Home

Purpose:

- recent runs
- server readiness summary
- recent results
- quick start entry points

Do not make Home feel like a metrics dashboard.

### 9.2 Servers

Purpose:

- connection and trust state
- health / readiness
- bootstrap and runner authority

#### Resource occupancy

In scientific/compute contexts, users care not only about liveness but about whether the machine is overloaded.

Include a restrained secondary resource area:

- CPU mini bar
- Memory mini bar

These are awareness tools, not dashboard centerpieces.

### 9.3 Projects

Purpose:

- organize project entities
- connect inputs/uploads to runs

### 9.4 Runs

Purpose:

- run list
- status/stage visibility
- path to run detail

### 9.5 Results

Purpose:

- result discovery
- traceability to source runs
- path to result detail

## 10. Run Detail Scheme

### 10.1 Header

Run detail should include:

- breadcrumb
- run title / runId
- status badge
- source project/server context
- requestId copy affordance

### 10.2 Tabs

- Overview
- Events
- Logs
- Outputs
- Spec

### 10.3 Logs rule

Logs are part of the detail page and should not feel like the primary black-terminal experience.

## 11. Result Detail Scheme

### 11.1 Header

Result detail should include:

- breadcrumb
- result title
- source run
- export/download action

### 11.2 Tabs

- Overview
- Files
- Preview
- Metadata
- Raw JSON

### 11.3 Preview selector

Preview uses a **top artifact selector**, not a left preview tree, for v1.

Reason:

- keeps visual focus on content
- avoids turning result detail into a file browser
- works better for large CSV/text preview contexts

### 11.4 Safe preview rule

For scientific files:

- text preview should use bounded content (e.g. first 100 lines)
- table preview should use bounded rows
- large files must not be fully read into UI
- unsupported types should fall back cleanly to download

### 11.5 File list cues

Files tab should include lightweight type cues:

- file suffix hints
- file-type icon cues

This improves scanability without requiring a full file tree.

## 12. Status and Badge Style

Status badges should use:

- light background
- darker text
- no overly bright “traffic light” saturation

The UI should feel calm and precise even when showing failure.

## 13. Approved Figma Frames

The initial Figma exploration should cover these four frames:

1. **Workspace Shell / Home**
2. **Servers List**
3. **Run Detail**
4. **Result Detail**

These four are enough to lock:

- shell rhythm
- hierarchy
- tabs
- breadcrumb treatment
- server mini bars
- result preview selector

## 14. Figma Notes

When drawing in Figma:

- preserve the subtle surface contrast between app background and content area
- do not over-card the interface
- keep tabs light
- keep breadcrumb quiet
- include a terminal button status variant

## 15. Non-Goals for This Scheme

This UI scheme does not yet define:

- full compare mode
- full design system token set
- advanced chart language
- AI copilot surface
- multi-pane analytical workbench behaviors

Those can follow once the core shell and object pages are stable.

