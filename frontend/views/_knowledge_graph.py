"""LECTIO — Knowledge Graph Page"""
import streamlit as st
import plotly.graph_objects as go
from utils.session_utils import get_client, safe_api_call
from components.ui_components import empty_state

NODE_COLOURS = {
    "course":     "#4F46E5",
    "module":     "#0EA5E9",
    "week":       "#10B981",
    "topic":      "#F59E0B",
    "clo":        "#EF4444",
    "assessment": "#8B5CF6",
}


def show_knowledge_graph():
    st.title("Knowledge Graph")
    st.caption("Interactive view of course structure — modules, topics, CLOs, and assessments.")
    client = get_client()

    courses_data, err = safe_api_call(client.list_courses)
    if err:
        st.error(err); return

    courses = (courses_data or {}).get("courses", [])
    if not courses:
        empty_state("No Courses", "Create a course to view its knowledge graph."); return

    opts   = {f"{c['code']} — {c['title']}": c["id"] for c in courses}
    label  = st.selectbox("Course", list(opts.keys()))
    cid    = opts[label]

    col1, col2 = st.columns([3, 1])
    with col2:
        show_clos       = st.checkbox("Show CLOs", value=True)
        show_assessments = st.checkbox("Show Assessments", value=True)
        depth_limit     = st.slider("Max topics shown", 5, 30, 15)

    # Load data
    modules,     merr = safe_api_call(client.list_modules, cid)
    assessments, aerr = safe_api_call(client.list_assessments, cid)

    nodes_x, nodes_y, node_text, node_colour, node_size = [], [], [], [], []
    edge_x, edge_y = [], []
    hover_text     = []

    # Course root node
    course_info = next((c for c in courses if c["id"] == cid), {})
    _add_node(0, 0, course_info.get("code","Course"),
              "course", nodes_x, nodes_y, node_text, node_colour, node_size, hover_text,
              f"Course: {course_info.get('title','')}")

    topic_count = 0
    for mi, mod in enumerate(modules or []):
        mx = (mi - len(modules or []) / 2) * 3
        my = -1.5
        _add_node(mx, my, mod["title"][:20], "module",
                  nodes_x, nodes_y, node_text, node_colour, node_size, hover_text,
                  f"Module {mod['sequence_number']}: {mod['title']}")
        _add_edge(0, 0, mx, my, edge_x, edge_y)

        if show_clos:
            clos, _ = safe_api_call(client.list_clos, cid, mod["id"])
            for ci, clo in enumerate(clos or []):
                cx = mx + (ci - len(clos or []) / 2) * 1.2
                cy = -3.0
                label_short = (clo.get("code") or f"CLO{ci+1}")
                _add_node(cx, cy, label_short, "clo",
                          nodes_x, nodes_y, node_text, node_colour, node_size, hover_text,
                          clo["text"][:100])
                _add_edge(mx, my, cx, cy, edge_x, edge_y)
                if topic_count >= depth_limit:
                    break
            topic_count += len(clos or [])

    if show_assessments:
        for ai, a in enumerate(assessments or []):
            ax = (ai - len(assessments or []) / 2) * 2.5
            ay = -4.5
            _add_node(ax, ay, a["title"][:18], "assessment",
                      nodes_x, nodes_y, node_text, node_colour, node_size, hover_text,
                      f"{a.get('type','').title()} | Weight: {a.get('weight_percent',0):.0f}%")
            _add_edge(0, 0, ax, ay, edge_x, edge_y)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y,
        mode="lines",
        line=dict(width=1, color="#CBD5E1"),
        hoverinfo="none",
    ))
    fig.add_trace(go.Scatter(
        x=nodes_x, y=nodes_y,
        mode="markers+text",
        marker=dict(size=node_size, color=node_colour, line=dict(width=2, color="white")),
        text=node_text,
        textposition="bottom center",
        hovertext=hover_text,
        hoverinfo="text",
    ))

    # Legend
    for ntype, colour in NODE_COLOURS.items():
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=10, color=colour),
            name=ntype.title(), showlegend=True,
        ))

    fig.update_layout(
        height=600,
        showlegend=True,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        plot_bgcolor="#FAFAFA",
        margin=dict(t=20, b=20, l=20, r=20),
    )
    with col1:
        st.plotly_chart(fig, use_container_width=True)

    # Legend table
    st.divider()
    st.markdown("#### Node Legend")
    cols = st.columns(len(NODE_COLOURS))
    for i, (ntype, colour) in enumerate(NODE_COLOURS.items()):
        cols[i].markdown(
            f"<span style='background:{colour}; color:white; padding:2px 8px; "
            f"border-radius:4px;'>{ntype.title()}</span>",
            unsafe_allow_html=True,
        )


def _add_node(x, y, label, node_type, xs, ys, texts, colours, sizes, hovers, hover):
    xs.append(x); ys.append(y); texts.append(label)
    colours.append(NODE_COLOURS.get(node_type, "#6B7280"))
    sizes.append({"course": 30, "module": 22, "week": 16,
                  "topic": 14, "clo": 12, "assessment": 18}.get(node_type, 14))
    hovers.append(hover)


def _add_edge(x1, y1, x2, y2, edge_x, edge_y):
    edge_x += [x1, x2, None]
    edge_y += [y1, y2, None]
