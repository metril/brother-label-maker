import { useState } from "react";
import type { HomeboxTreeItem } from "../api/types";

interface HomeboxLocationTreeProps {
  nodes: HomeboxTreeItem[];
  selectedId: string | null;
  onSelect: (node: HomeboxTreeItem | null) => void;
}

/** The browse page's left location tree (task 3.4): a collapsible nested
 * list straight from GET /api/homebox/entities/tree, filtered to
 * `type === "location"` at every level -- the tree can carry item nodes too
 * once `with_items=true` is passed, which this page never does (see hooks/
 * useHomeboxTree.ts), so the filter here is defensive, not load-bearing.
 * "All locations" always sits above the tree itself and clears the active
 * parent filter (`onSelect(null)`). Clicking any OTHER node sets it as the
 * active parent filter -- pages/Homebox.tsx's own `parent_id`. */
export function HomeboxLocationTree({ nodes, selectedId, onSelect }: HomeboxLocationTreeProps) {
  const roots = nodes.filter((node) => node.type === "location");

  return (
    <ul className="flex flex-col gap-0.5">
      <li>
        <button
          type="button"
          aria-current={selectedId === null ? "true" : undefined}
          onClick={() => onSelect(null)}
          className={`w-full rounded-md px-2 py-1 text-left text-[13px] font-medium ${
            selectedId === null ? "bg-amber-500/15 text-amber-300" : "text-deck-200 hover:bg-deck-800"
          }`}
        >
          All locations
        </button>
      </li>
      {roots.map((node) => (
        <HomeboxTreeNode key={node.id} node={node} depth={0} selectedId={selectedId} onSelect={onSelect} />
      ))}
    </ul>
  );
}

interface HomeboxTreeNodeProps {
  node: HomeboxTreeItem;
  depth: number;
  selectedId: string | null;
  onSelect: (node: HomeboxTreeItem) => void;
}

function HomeboxTreeNode({ node, depth, selectedId, onSelect }: HomeboxTreeNodeProps) {
  // Top-level nodes start expanded (there are usually only a handful of
  // root locations -- a garage, a house, ...); deeper levels start
  // collapsed so a large tree doesn't dump every leaf on screen at once.
  const [expanded, setExpanded] = useState(depth === 0);
  const children = node.children.filter((child) => child.type === "location");
  const hasChildren = children.length > 0;
  const isActive = node.id === selectedId;

  return (
    <li>
      <div className="flex items-center gap-1" style={{ paddingLeft: depth * 14 }}>
        {hasChildren ? (
          <button
            type="button"
            aria-expanded={expanded}
            aria-label={expanded ? `Collapse ${node.name}` : `Expand ${node.name}`}
            onClick={() => setExpanded((e) => !e)}
            className="flex h-5 w-5 shrink-0 items-center justify-center text-[11px] text-deck-400 hover:text-deck-200"
          >
            {expanded ? "▾" : "▸"}
          </button>
        ) : (
          <span aria-hidden className="h-5 w-5 shrink-0" />
        )}
        <button
          type="button"
          aria-current={isActive ? "true" : undefined}
          onClick={() => onSelect(node)}
          title={node.name}
          className={`min-w-0 flex-1 truncate rounded-md px-2 py-1 text-left text-[13px] font-medium ${
            isActive ? "bg-amber-500/15 text-amber-300" : "text-deck-200 hover:bg-deck-800"
          }`}
        >
          {node.name}
        </button>
      </div>
      {hasChildren && expanded && (
        <ul className="flex flex-col gap-0.5">
          {children.map((child) => (
            <HomeboxTreeNode key={child.id} node={child} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} />
          ))}
        </ul>
      )}
    </li>
  );
}
