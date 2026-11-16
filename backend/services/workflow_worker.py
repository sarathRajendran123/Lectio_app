"""Isolated LangGraph worker, terminable by parent on cancellation or timeout."""
import sys
# stdout carries exactly one JSON document to the parent. Anything else that writes to stdout (SQL echo with
# DEBUG=true, a stray print, a library) goes to stderr, which the parent keeps for its error log.
RESULT, sys.stdout = sys.stdout, sys.stderr
import json
from dataclasses import asdict, is_dataclass
from agents.graph.state import initial_state

def main():
    from agents.graph.workflow import workflow_app
    state=initial_state(sys.argv[1],sys.argv[2],sys.argv[3])
    from agents.stakeholder_agent import StakeholderAgent
    state['reviewer_preferences']=StakeholderAgent()._load_preferences(sys.argv[3])
    result=workflow_app.invoke(state, config={'recursion_limit':24})
    def encode(value):
        if is_dataclass(value): return asdict(value)
        if hasattr(value,'value'): return value.value
        return str(value)
    RESULT.write(json.dumps(dict(result), default=encode))
    RESULT.flush()

if __name__ == '__main__': main()
