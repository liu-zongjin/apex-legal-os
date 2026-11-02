"""Public research planning without topic branches, case IDs or canned answers."""
from .case_issue import build_search_constraints


def generic_case_plan(question):
    question=str(question or '').strip()
    return {'original_query':question,'core_issue':question,'essential_terms':[],
            'required_term_groups':[],'strict_issue_match':False,'fact_fingerprint':{},
            'queries':[{'id':'original','query':question[:220],'viewpoint':'neutral'}],
            'search_constraints':build_search_constraints(question)}
