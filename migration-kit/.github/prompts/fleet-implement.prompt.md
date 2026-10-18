---
description: CLI alternative to the orchestrator - paste into `copilot` as /fleet after the design is approved
---
/fleet Implement the approved design. Tasks:
1. @infra: ${input:task1:Infra task - Docker, AWS, Azure}
2. @data: ${input:task2:Database task}. Depends on 1.
3. @ui: ${input:task3:UI task}. Depends on 2.
Rules: each task touches only its own repo. No two tasks edit the same file.
Edits to the central repo are done last, by you, after all tasks finish.
