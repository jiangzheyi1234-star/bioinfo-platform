"""Pure function tests for integrated history open-results state."""

from pathlib import Path
import subprocess


MODULE_PATH = Path("ui/pages/detection_page_assets/results/open_results_state.js")


def _run_node_test(script: str) -> None:
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout or "node test failed")


def test_open_results_state_module_exists():
    assert MODULE_PATH.exists()


def test_open_results_state_register_trim_pin_and_close():
    module_ref = "./" + str(MODULE_PATH).replace("\\", "/")
    script = f"""
const stateApi = require({module_ref!r});

let state = stateApi.normalizeState({{ maxOpenResults: 2 }});
state = stateApi.reduceIntegratedOpenResultsState(state, {{
  type: 'register_result',
  payload: {{ resultKey: 'primer_design::exec_1', entity: {{ title: 'r1' }} }}
}});
state = stateApi.reduceIntegratedOpenResultsState(state, {{
  type: 'register_result',
  payload: {{ resultKey: 'primer_design::exec_2', entity: {{ title: 'r2' }} }}
}});
state = stateApi.reduceIntegratedOpenResultsState(state, {{
  type: 'set_pinned',
  payload: {{ resultKey: 'primer_design::exec_1', pinned: true }}
}});
state = stateApi.reduceIntegratedOpenResultsState(state, {{
  type: 'register_result',
  payload: {{ resultKey: 'primer_design::exec_3', entity: {{ title: 'r3' }} }}
}});
state = stateApi.reduceIntegratedOpenResultsState(state, {{
  type: 'trim_open_results',
  payload: {{ maxOpenResults: 2 }}
}});

if (!state.openKeys.includes('primer_design::exec_1')) throw new Error('pinned result should be preserved');
if (!state.openKeys.includes('primer_design::exec_3')) throw new Error('latest result should remain open');
if (state.openKeys.includes('primer_design::exec_2')) throw new Error('oldest unpinned result should be trimmed');

state = stateApi.reduceIntegratedOpenResultsState(state, {{
  type: 'close_result',
  payload: {{ resultKey: 'primer_design::exec_3' }}
}});

if (state.activeKey !== 'primer_design::exec_1') throw new Error('closing active result should fall back to remaining pinned result');
"""
    _run_node_test(script)


def test_open_results_state_builds_stable_result_key():
    module_ref = "./" + str(MODULE_PATH).replace("\\", "/")
    script = f"""
const stateApi = require({module_ref!r});
const resultKey = stateApi.buildHistoryResultKey('primer_design', 'exec_demo');
if (resultKey !== 'primer_design::exec_demo') throw new Error('unexpected result key: ' + resultKey);
"""
    _run_node_test(script)
