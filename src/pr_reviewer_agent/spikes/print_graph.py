from pathlib import Path

from pr_reviewer_agent.graph import review_graph

graph = review_graph.get_graph()
out = Path("review_graph.png")
out.write_bytes(graph.draw_mermaid_png())
print(f"saved {out.resolve()}")