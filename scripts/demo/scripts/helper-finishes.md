# helper-finishes
title: A background helper finishes and says so
length: 60
setup: A real, harmless task: a read-only search or a build in a scratch folder.
proof: result=ANSWERED && transcript~background
## steps
- show Hand a task to a background helper, carry on working, hear it report back.
- say 9 "In the background, find the five largest files in my downloads folder"
- wait 8
- run wispd task list
- wait 25
- show The helper says it is done.
- wait 6
## captions
readme: I handed off a search and kept working. The helper finished on its own and said so out loud.
release: Background helpers report back by voice when they finish.
omarchy: Fire and forget a read-only job, get a spoken result later. The task list shows what is running.
x: Handed a search to a background helper, kept working, it told me when it finished.
short: It finished and told me.
