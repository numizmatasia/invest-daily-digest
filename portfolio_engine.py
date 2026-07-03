"""
Portfolio Engine v1.0

Calculates portfolio concentration and exposes normalized portfolio state
for decision_engine.
"""

from collections import defaultdict

def analyze_portfolio(portfolio: dict):
    result={"portfolios":{}}
    for pname, assets in portfolio.items():
        total=sum(v for v in assets.values() if isinstance(v,(int,float)))
        info=[]
        for t,v in assets.items():
            if isinstance(v,(int,float)):
                info.append({"ticker":t,"weight":round(v,2),
                             "level":"large" if v>=15 else "medium" if v>=5 else "small"})
        info.sort(key=lambda x:x["weight"], reverse=True)
        result["portfolios"][pname]={
            "total_weight":round(total,2),
            "positions":info
        }
    return result
