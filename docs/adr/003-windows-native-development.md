# ADR-003: Windows-Native Development with Linux Deployment Path

**Status**: Accepted  
**Date**: 2026-07-13  
**Context**: Planning phase

## Decision

Develop natively on Windows with PowerShell scripts. Preserve Linux deployment path through environment-agnostic Python code.

## Context

Target audience: Persian developers and researchers, many on Windows.
Need local-first development but eventual VPS deployment.

Options considered:
1. **Linux-first** (Bash scripts, assumes Linux/macOS/WSL)
2. **Windows-first** (PowerShell scripts, native Windows)
3. **Platform-agnostic** (Python scripts only, no shell helpers)

## Rationale

Chosen: Windows-first with Linux path preserved (#2)

**Why Windows-first**:
- Primary dev environment for target users
- No WSL requirement (barrier to entry)
- PowerShell available on all Windows 10/11
- Better native Docker Desktop integration
- uv works natively on Windows

**Why not Linux-first**:
- Forces WSL on Windows users
- Git Bash/MSYS limited compared to real Bash
- Cultural fit: target users often Windows-native

**Why not Python-only**:
- Shell scripts provide better UX for common tasks
- PowerShell error handling cleaner than Python subprocess
- Script composition easier (run-all.ps1)

**Linux deployment preserved**:
- All logic in Python (platform-agnostic)
- Scripts are thin wrappers around Python CLI
- Docker Compose works identically
- Future: Generate Bash equivalents from templates

## Implementation

Development (Windows):
```
Developer → PowerShell scripts → Python CLI → Docker PostgreSQL
```

Production (Linux VPS - future):
```
Cron → Bash scripts (or Python CLI directly) → App container → DB container
```

**Constitution principle**: "Windows-Native Development" - development workflow must work on Windows without WSL.

## Consequences

**Positive**:
- Lower barrier to entry for Windows developers
- Better Windows debugging experience
- Native performance (no VM/WSL overhead)
- Professional PowerShell scripts signal production-quality

**Negative**:
- Must maintain script parity if adding Bash versions
- Harder for Linux/macOS contributors
- PowerShell less familiar to Linux-first developers

**Mitigations**:
- Keep scripts thin (business logic in Python)
- Document script behavior clearly
- Future: Auto-generate Bash from PowerShell templates
- Python CLI always works directly (scripts optional)

## Trade-offs Accepted

- **Script duplication cost** for better developer experience
- **PowerShell learning curve** for broader Windows support
- **Two execution paths** (scripts vs direct CLI) for flexibility

## Success Criteria

Acceptable if:
- Windows developer can run entire workflow without WSL
- Python code runs identically on Windows and Linux
- Docker Compose config identical across platforms
- Future Linux deployment doesn't require code changes
