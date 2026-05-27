# PT Gary

AI-powered personal trainer. Programs your workouts, tracks your progress, manages progressive overload, and keeps your muscles guessing.

**How it works:**

1. **PT Gary designs your cycle** — exercises, sets, reps, starting weights
2. **You log via Telegram** — `bench 80 10/10/9` takes 5 seconds between sets
3. **Gary tracks everything** — weight progression, stall detection, exercise rotation
4. **Dashboard shows progress** — strength curves, volume trends, bodyweight tracking

---

## Architecture

```
Telegram → Hermes (PT Gary) → MD files → GitHub Pages Dashboard
                              ↑
                    Progressive overload engine
                    Exercise rotation logic
                    Stall detection
```

## Status

🚧 Phase 1 — Foundation (building now)

---

*Built and operated by [Gary](https://github.com/gary-the-ai-2026) — Josh Hancock's personal AI assistant.*
