// Sample of the component contract the plotting agent asks the LLM to follow:
// export `Figure`, import only react + remotion, final frame shows the full figure.
import React from "react";
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";

const stages = ["Raw materials", "Outline", "Literature", "Sections", "Refinement"];
const colors = ["#4C78A8", "#F58518", "#54A24B", "#B279A2", "#E45756"];

export const Figure: React.FC = () => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const boxW = width / (stages.length + 1.5);
  const gap = (width - boxW * stages.length) / (stages.length + 1);
  const y = height / 2 - 90;

  return (
    <AbsoluteFill style={{backgroundColor: "white", fontFamily: "Helvetica, Arial, sans-serif"}}>
      <svg width={width} height={height}>
        <defs>
          <marker id="arrow" markerWidth="24" markerHeight="24" refX="22" refY="12" orient="auto"
            markerUnits="userSpaceOnUse">
            <path d="M0,0 L24,12 L0,24 z" fill="#555" />
          </marker>
        </defs>
        {stages.map((label, i) => {
          const appear = spring({frame: frame - i * 12, fps, config: {damping: 200}});
          const x = gap + i * (boxW + gap);
          const arrowOpacity = interpolate(frame, [i * 12 + 10, i * 12 + 20], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          return (
            <g key={label} opacity={appear}>
              <rect x={x} y={y} width={boxW} height={180} rx={24} fill={colors[i]} fillOpacity={0.18}
                stroke={colors[i]} strokeWidth={5} />
              <text x={x + boxW / 2} y={y + 102} textAnchor="middle" fontSize={40} fill="#222">{label}</text>
              {i < stages.length - 1 && (
                <line x1={x + boxW + 8} y1={y + 90} x2={x + boxW + gap - 12} y2={y + 90} stroke="#555"
                  strokeWidth={5} markerEnd="url(#arrow)" opacity={arrowOpacity} />
              )}
            </g>
          );
        })}
      </svg>
    </AbsoluteFill>
  );
};
