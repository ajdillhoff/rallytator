# RallyTator
RallyTator is a fast and user-friendly annotation tool primarily used for annotating objects in videos for RallyLens, a Tennis analytics platform. Annotations are semi-automated through the aid of open-source models (YOLO, SAM3, CoTracker, etc.). Efficient keybinds make annotating much easier and streamline the user's workflow.

# Tasks

RallyTator's primary job is to produce the annotation *substrate* — the per-frame
geometry a downstream pipeline consumes:

- Pose (Player, Racquet, Court)
- Point (Ball) — labeled only while *ballistic* (in flight)

**Actions** (Forehand Swing, Backhand Swing, Forehand Volley, Backhand Volley, Serve,
Lob) are **derived**, not annotated from scratch: a downstream pipeline infers them from
pose + court + ball. RallyTator supports *reviewing and correcting* inferred Actions to
build train/eval ground-truth. See [CONTEXT.md](CONTEXT.md) and
[docs/adr/](docs/adr/) for the domain model and decisions.

# Primary Data
First-class support for video and frame-by-frame annotation.