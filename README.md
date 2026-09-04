# FPL GitHub Mirror

A public, automation-friendly snapshot of league 351382 / entry 4765608.

- GitHub Actions refreshes `snapshot/fpl.json` every 15 minutes.
- It queries the official public FPL API directly; no FPL login or secret is required.
- It automatically detects the newest Gameweek whose locked picks are public.
- It includes every league manager, current standings, squads, captain/vice, active chip, history, completed transfers, and player/team lookup.
- Pre-deadline unrevealed rival transfers are intentionally unavailable.

Once published, ChatGPT can use the repo/file as a stable fallback even when `*.vercel.app` is inaccessible from a runtime.
