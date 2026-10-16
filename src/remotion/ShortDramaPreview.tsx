import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

export type ShortDramaPreviewProps = {
  title: string;
  subtitle: string;
};

export const ShortDramaPreview: React.FC<ShortDramaPreviewProps> = ({ title, subtitle }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 18], [0, 1], { extrapolateRight: "clamp" });
  const translateY = interpolate(frame, [0, 18], [32, 0], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        alignItems: "center",
        background: "linear-gradient(155deg, #131b2b 0%, #332448 55%, #a34248 100%)",
        color: "#fff8ef",
        fontFamily: "sans-serif",
        justifyContent: "center",
        textAlign: "center",
      }}
    >
      <div style={{ opacity, transform: `translateY(${translateY}px)`, padding: 80 }}>
        <div style={{ color: "#f4bd87", fontSize: 28, letterSpacing: 8, marginBottom: 30 }}>
          SHORT DRAMA · 9:16
        </div>
        <h1 style={{ fontSize: 88, fontWeight: 700, lineHeight: 1.2, margin: 0 }}>{title}</h1>
        <p style={{ color: "#e8d9d3", fontSize: 34, marginTop: 40 }}>{subtitle}</p>
        <div style={{ backgroundColor: "#f4bd87", height: 4, margin: "55px auto 0", width: 120 }} />
      </div>
    </AbsoluteFill>
  );
};
