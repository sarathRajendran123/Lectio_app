"""Isolated LangGraph worker, terminable by parent on cancellation or timeout."""
import json
import sys
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
    print(json.dumps(dict(result), default=encode))

if __name__ == '__main__': main()
