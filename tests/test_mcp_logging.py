import subprocess
import sys


def test_cli_appends_application_logs_to_file(tmp_path):
    log = tmp_path / 'mcp.log'
    log.write_text('previous run\n')
    result = subprocess.run([
        sys.executable, '-m', 'galet_tools.mcp.server',
        '--config', str(tmp_path / 'missing.json'),
        '--log-level', 'INFO', '--log-file', str(log),
    ], capture_output=True, text=True)
    assert result.returncode == 2
    assert log.read_text().startswith('previous run\n')
    assert 'mcp_process_start' in log.read_text()
    assert 'mcp_start_failed' in log.read_text()
    assert 'mcp_process_start' in result.stderr


def test_cli_reports_unwritable_log_destination(tmp_path):
    result = subprocess.run([
        sys.executable, '-m', 'galet_tools.mcp.server',
        '--log-file', str(tmp_path / 'missing' / 'mcp.log'),
    ], capture_output=True, text=True)
    assert result.returncode == 2
    assert 'cannot open log file' in result.stderr
