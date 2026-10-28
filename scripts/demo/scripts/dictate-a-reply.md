# dictate-a-reply
title: Dictate a reply into the focused field
length: 40
setup: Open a real compose window or text field with a short message to answer. Use a throwaway account, nothing private in view.
proof: result=ANSWERED && transcript~reply
## steps
- show Say what to reply; Wisp writes it into the field and waits for you to send it.
- say 10 "Reply that Thursday works and I will bring the notes"
- wait 10
- human 4 Read the text in the field, then close the window without sending
## captions
readme: Dictating a reply into the open field. I read it and close without sending: nothing is sent for me.
release: Dictation into the focused field, confirm before anything leaves.
omarchy: Hold, speak, the words land in the focused window. Nothing is sent without you.
x: Dictated a reply into the open field. I read it, then closed without sending. Nothing goes out unless I send it.
short: Say it, it is typed.
