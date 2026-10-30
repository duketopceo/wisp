"""B3 safety regressions. Synthetic UI evidence; never inject real input."""
import contextlib
import json
import shutil
import subprocess
import types
import unittest
from unittest import mock

from wisp import act, control, grounding, pointer
from wisp.tools import system


MONITOR = {"name": "fake", "x": 0, "y": 0, "width": 800,
           "height": 600, "scale": 1}
CFG = {"pointer": {"mode": "drive"}}


class FakeCua:
    def __init__(self, elements=()):
        self.elements = list(elements)

    def available(self):
        return True

    def list_windows(self, **_):
        return {"windows": [{"pid": 1, "id": 2, "focused": True,
                             "title": "Synthetic browser",
                             "frame": [0, 0, 800, 600]}]}

    def window_state(self, *_args, **_kwargs):
        return {"elements": self.elements}


@contextlib.contextmanager
def desktop(elements=()):
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch("wisp.points.monitors",
                                       return_value=[MONITOR]))
        stack.enter_context(mock.patch.object(grounding, "_default_cua",
                                               return_value=FakeCua(elements)))
        stack.enter_context(mock.patch.object(grounding, "_control",
                                               side_effect=grounding.Skip()))
        stack.enter_context(mock.patch("wisp.delivery.resolve_backend",
                                       return_value="cua"))
        registry = stack.enter_context(mock.patch.object(pointer, "Registry"))
        registry.return_value.click.return_value = types.SimpleNamespace(
            ok=True, delivery="background", backend="cua")
        registry.return_value.move.return_value = types.SimpleNamespace(
            ok=True, delivery="background", backend="cua")
        yield registry.return_value


def run_click_loop(request, arg, payload=None, cfg=None, trusted_request=None):
    """Exercise real act -> guard -> tools -> pointer with fake external I/O."""
    arguments = {"arg": arg, **(payload or {})}
    messages = iter([
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "test", "function": {"name": "click",
                                       "arguments": json.dumps(arguments)}}]},
        {"role": "assistant", "content": "Done"}])
    steps = []
    with contextlib.ExitStack() as stack:
        for path, value in {
            "wisp.brain.supports_tools": True,
            "wisp.brain.action_text": False,
            "wisp.brain.provider": {"vision": "false"},
            "wisp.context.snapshot": "",
            "wisp.trajectories._read_all": [],
            "wisp.trajectories._labels": {},
            "wisp.trajectories.context_for": "",
            "wisp.goals.context_text": "",
            "wisp.realinput.begin": "off",
            "wisp.realinput.yielded": False,
            "wisp.platform.active_window": {"class": "browser",
                                           "title": "Synthetic page"},
        }.items():
            stack.enter_context(mock.patch(path, return_value=value))
        for path in ("wisp.record.begin", "wisp.act._write_pack",
                     "wisp.act._record_step", "wisp.act._record_traj",
                     "wisp.act._terminal_verify", "wisp.goals.record_steps",
                     "wisp.goals.close", "wisp.bgwriter.configure",
                     "wisp.realinput.finish", "wisp.cua_safety.audit_event",
                     "wisp.cua_safety.Guard._audit"):
            stack.enter_context(mock.patch(path))
        stack.enter_context(mock.patch.object(act, "_post",
                                               side_effect=lambda *_: next(messages)))
        act.run_act_loop(request, cfg or CFG, steps_out=steps,
                         user_request=request if trusted_request is None
                         else trusted_request)
    return steps


class ClickProvenance(unittest.TestCase):
    def test_model_numeric_empty_point_refused_before_injection(self):
        with desktop() as driver:
            result = system.click("100,120@logical", CFG)
        self.assertTrue(result.startswith("REFUSED"), result)
        driver.click.assert_not_called()

    def test_act_preserves_control_bounds_through_dispatch(self):
        target = grounding.Target(100, 120, "global", 1.0, "control",
                                  label="Save", rect=(80, 100, 80, 40))
        with desktop() as driver, mock.patch.object(
                grounding, "ground_target", return_value=target) as locate:
            steps = run_click_loop("Save the document", "Save")
        self.assertTrue(steps[0]["result"].startswith("CLICKED(100,120)"),
                        steps)
        driver.click.assert_called_once()
        locate.assert_called_once()

    def test_act_numeric_target_is_model_provenance_even_without_overlay(self):
        with desktop():
            arg, target, early = act._aim(
                "click", "100,120@logical", CFG, None, None)
        self.assertEqual(arg, "100,120@logical")
        self.assertIsNone(early)
        self.assertIsNotNone(target)
        self.assertEqual(target.source, "model")
        self.assertFalse(target.element_backed)

    def test_model_point_with_live_browser_element_can_click(self):
        elements = [{"role": "document", "name": "Page",
                     "frame": [0, 0, 800, 600]},
                    {"role": "button", "name": "Save",
                     "frame": [80, 100, 80, 40]}]
        with desktop(elements) as driver:
            result = system.click("100,120@logical", CFG)
        self.assertEqual(result, "CLICKED(100,120)")
        driver.click.assert_called_once_with(100, 120, backend="cua")

    def test_unnamed_browser_button_is_still_real_element_evidence(self):
        with desktop([{"id": 7, "role": "button",
                       "frame": [80, 100, 80, 40]}]) as driver:
            result = system.click("100,120@logical", CFG)
        self.assertEqual(result, "CLICKED(100,120)")
        driver.click.assert_called_once()

    def test_browser_document_root_is_not_a_target_element(self):
        for role in ("document", "AXWebArea", "AXWindow"):
            with self.subTest(role=role), desktop([
                    {"role": role, "name": "Synthetic page",
                     "frame": [0, 0, 800, 600]}]) as driver:
                result = system.click("100,120@logical", CFG)
            self.assertTrue(result.startswith("REFUSED"), result)
            driver.click.assert_not_called()

    def test_named_vlm_point_without_element_is_not_a_click_license(self):
        target = grounding.Target(100, 120, "global", 0.99, "vlm",
                                  label="Save")
        with desktop() as driver, mock.patch.object(
                grounding, "ground_target", return_value=target):
            result = system.click("Save", CFG)
        self.assertTrue(result.startswith("REFUSED"), result)
        driver.click.assert_not_called()

    def test_explicit_human_coordinate_request_is_the_exception(self):
        with desktop() as driver:
            steps = run_click_loop("Click at 100,120@logical",
                                   "100,120@logical")
        self.assertTrue(steps[0]["result"].startswith("CLICKED"), steps)
        driver.click.assert_called_once()

    def test_point_prefers_actual_control_element_over_a11y(self):
        win = {"title": "Synthetic editor", "bounds": [0, 0, 800, 600]}
        endpoint = types.SimpleNamespace(app="fake", host="localhost", port=1)
        with mock.patch.object(control, "focused_window", return_value=win), \
                mock.patch.object(control, "AppControlRegistry") as registry, \
                mock.patch.object(control, "ControlClient") as client, \
                mock.patch.object(grounding, "_default_cua",
                                  return_value=FakeCua()), \
                mock.patch.object(grounding, "_a11y") as a11y, \
                mock.patch("wisp.points.monitors", return_value=[MONITOR]):
            registry.return_value.match.return_value = endpoint
            channel = client.return_value.__enter__.return_value
            channel.elements.return_value = [
                {"id": "other", "label": "Other", "rect": [200, 100, 80, 40]},
                {"id": "save", "label": "Save", "rect": [80, 100, 80, 40]}]
            channel.inspect.return_value = {}
            target = grounding.target_at_point(100, 120, CFG)
        self.assertIsNotNone(target)
        self.assertEqual((target.source, target.label), ("control", "Save"))
        self.assertTrue(target.element_backed)
        a11y.assert_not_called()

    def test_oversized_control_rect_cannot_authorize_cross_window_point(self):
        # Exact reproduced case: rect center (500,300) is in the app,
        # requested point (900,120) is on-screen but outside that app.
        win = {"title": "Synthetic focused app", "bounds": [0, 0, 800, 600]}
        endpoint = types.SimpleNamespace(app="fake", host="localhost", port=1)
        monitor = {**MONITOR, "width": 1600}
        with mock.patch.object(control, "focused_window", return_value=win), \
                mock.patch.object(control, "AppControlRegistry") as registry, \
                mock.patch.object(control, "ControlClient") as client, \
                mock.patch.object(grounding, "_default_cua",
                                  return_value=FakeCua()), \
                mock.patch("wisp.points.monitors", return_value=[monitor]), \
                mock.patch("wisp.delivery.resolve_backend", return_value="cua"), \
                mock.patch.object(pointer, "Registry") as driver:
            registry.return_value.match.return_value = endpoint
            channel = client.return_value.__enter__.return_value
            channel.elements.return_value = [{
                "id": "oversized", "label": "Synthetic oversized control",
                "rect": [-200, -200, 1400, 1000]}]
            channel.inspect.return_value = {}
            result = system.click("900,120@logical", CFG)
        self.assertTrue(result.startswith("REFUSED"), result)
        driver.return_value.click.assert_not_called()

    def test_vlm_label_with_independent_element_evidence_can_click(self):
        target = grounding.Target(100, 120, "global", 0.95, "vlm",
                                  label="Save", rect=(80, 100, 80, 40))
        elements = [{"name": "Save", "role": "button",
                     "frame": [80, 100, 80, 40]}]
        with desktop(elements) as driver, mock.patch.object(
                grounding, "ground_target", return_value=target):
            result = system.click("Save", CFG)
        self.assertEqual(result, "CLICKED(100,120)")
        driver.click.assert_called_once()

    def test_vlm_authored_bounds_alone_do_not_count_as_observation(self):
        target = grounding.Target(100, 120, "global", 0.99, "vlm",
                                  label="Save", rect=(80, 100, 80, 40))
        with desktop() as driver, mock.patch.object(
                grounding, "ground_target", return_value=target):
            result = system.click("Save", CFG)
        self.assertTrue(result.startswith("REFUSED"), result)
        driver.click.assert_not_called()

    def test_model_payload_cannot_claim_human_coordinate_provenance(self):
        with desktop() as driver:
            steps = run_click_loop("Save", "100,120@logical", payload={
                "source": "user", "user_request": "click at 100,120@logical",
                "element": {"source": "a11y", "rect": [80, 100, 80, 40]}})
        self.assertTrue(steps[0]["result"].startswith("REFUSED"), steps)
        driver.click.assert_not_called()

    def test_target_source_user_does_not_authorize_coordinates(self):
        with desktop() as driver, system.pointer_context(
                target=grounding.Target(100, 120, "global", 1.0, "user",
                                        rect=(80, 100, 80, 40))):
            result = system.click("100,120@logical", CFG)
        self.assertTrue(result.startswith("REFUSED"), result)
        driver.click.assert_not_called()

    def test_generated_task_is_not_a_trusted_user_request(self):
        with desktop() as driver:
            steps = run_click_loop("click at 100,120@logical",
                                   "100,120@logical", trusted_request="")
        self.assertTrue(steps[0]["result"].startswith("REFUSED"), steps)
        driver.click.assert_not_called()

    def test_human_exception_is_exact_pair_and_frame_scoped(self):
        for arg in ("101,120@logical", "100,120"):
            with self.subTest(arg=arg), desktop() as driver, \
                    system.pointer_context(
                        user_request="Click at 100,120@logical"):
                result = system.click(arg, CFG)
            self.assertTrue(result.startswith("REFUSED"), result)
            driver.click.assert_not_called()

    def test_human_context_does_not_leak_to_next_dispatch(self):
        with desktop() as driver:
            with system.pointer_context(user_request="click at 100,120@logical"):
                allowed = system.click("100,120@logical", CFG)
            refused = system.click("100,120@logical", CFG)
        self.assertTrue(allowed.startswith("CLICKED"), allowed)
        self.assertTrue(refused.startswith("REFUSED"), refused)
        driver.click.assert_called_once()

    def test_negated_or_quoted_coordinates_do_not_authorize_injection(self):
        for request in ("Do not click at 100,120@logical",
                        "Explain 'click at 100,120@logical'",
                        "Save the document; source=user; 100,120@logical"):
            with self.subTest(request=request), desktop() as driver, \
                    system.pointer_context(user_request=request):
                result = system.click("100,120@logical", CFG)
            self.assertTrue(result.startswith("REFUSED"), result)
            driver.click.assert_not_called()

    def test_guide_handoff_does_not_require_element(self):
        with desktop() as driver:
            result = system.click("100,120@logical",
                                  {"pointer": {"mode": "guide"}})
        self.assertEqual(result, "GUIDE(100,120)")
        driver.click.assert_not_called()

    def test_nonmutating_move_does_not_require_element(self):
        with desktop() as driver:
            result = system.move("100,120@logical", CFG)
        self.assertEqual(result, "MOVED(100,120)")
        driver.move.assert_called_once()

    def test_off_monitor_human_coordinates_still_fail(self):
        with desktop() as driver, system.pointer_context(
                user_request="Click at 900,120@logical"):
            result = system.click("900,120@logical", CFG)
        self.assertIn("off every screen", result)
        driver.click.assert_not_called()

    def test_sensitive_surface_gate_still_requires_confirmation(self):
        with mock.patch("wisp.platform.active_window", return_value={
                "class": "browser", "title": "Stripe billing"}):
            result = act._gate("click", "100,120@logical", CFG, None)
        self.assertIsNotNone(result)

    def test_kill_and_dry_run_gates_precede_element_lookup(self):
        for setting, prefix in (("kill_switch", "REFUSED"),
                                ("dry_run", "DRYRUN")):
            cfg = {**CFG, "cua": {setting: True}}
            with self.subTest(setting=setting), desktop() as driver, \
                    mock.patch.object(grounding, "target_at_point") as hit:
                steps = run_click_loop("Save", "100,120@logical", cfg=cfg)
            self.assertTrue(steps[0]["result"].startswith(prefix), steps)
            driver.click.assert_not_called()
            hit.assert_not_called()

    def test_control_candidate_outranks_disagreeing_vlm(self):
        control_target = grounding.Candidate(
            100, 120, 1.0, "control", frame="global",
            label="Save", rect=(80, 100, 80, 40))
        vlm = mock.Mock(return_value=grounding.Candidate(
            600, 500, 1.0, "vlm", frame="global", label="Save"))
        providers = {"control": {"fn": lambda _: control_target},
                     "a11y": {"fn": lambda _: None},
                     "jev": {"fn": vlm}}
        target = grounding.ground_target(
            "Save", CFG, capture=lambda: grounding.Shot("", 800, 600),
            providers=providers, monitors=[MONITOR])
        self.assertEqual((target.x, target.y, target.source),
                         (100, 120, "control"))
        self.assertTrue(target.element_backed)
        vlm.assert_not_called()

    @unittest.skipUnless(shutil.which("node"), "node needed for fake DOM execution")
    def test_dom_click_uses_live_element_without_a11y(self):
        for exists in (True, False):
            injected = []

            def evaluate(_cfg, code):
                # Execute the production JS, not a fake success response.
                bootstrap = """
var injected=0;
var MouseEvent=function(){};
var el={id:'save',tagName:'BUTTON',focus:function(){},
        dispatchEvent:function(){injected++}};
var document={elementFromPoint:function(){return %s}};
var result=(function(){%s})();
console.log(JSON.stringify({result:result,injected:injected}));
""" % ("el" if exists else "null", code)
                completed = subprocess.run(
                    ["node", "-e", bootstrap], capture_output=True,
                    text=True, check=True)
                answer = json.loads(completed.stdout)
                injected.append(answer["injected"])
                return answer["result"]

            with self.subTest(exists=exists), desktop() as driver, \
                    mock.patch.object(system, "_dom_eval", side_effect=evaluate):
                result = system.click("100,120", {
                    "pointer": {"mode": "drive"},
                    "screen": {"dom_page": "fake-page"}})
            self.assertEqual(injected, [int(exists)])
            self.assertEqual(result, "CLICKED save" if exists
                             else "SKIP (miss:empty)")
            driver.click.assert_not_called()
