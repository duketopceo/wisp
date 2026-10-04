"""Per-turn context shared by the four pipeline stages.

One TurnCtx lives for one push-to-talk cycle. Each stage reads what the
earlier ones filled in and writes its own outputs here, so the stage
functions stay free of long argument lists and the orchestrator in
wisp.pipeline can still reach `result`/`speaker` from its error paths.
"""


class TurnCtx:
    def __init__(self, cfg, state, wait_for_choice, wav, interrupted, sp,
                 turn, token, speculative, secs, model):
        self.cfg = cfg
        self.state = state                  # TurnState (or plain State)
        self.wait_for_choice = wait_for_choice
        self.wav = wav
        self.interrupted = interrupted
        self.sp = sp                        # trace.Spans
        self.turn = turn
        self.token = token                  # cancel.CancelToken
        self.speculative = speculative
        self.secs = secs
        self.model = model
        # capture
        self.text = ""
        # context
        self.harness = None
        self.context = ""
        self.detail = ""
        self.shot_b64 = None
        self.session_text = ""
        self.corr = None
        # route
        self.answers = {}
        # execute
        self.result = ""
        # speak
        self.speaker = None
        self.reply = ""
