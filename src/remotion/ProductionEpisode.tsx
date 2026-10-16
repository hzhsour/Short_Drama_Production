import React from "react";
import {
  AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, staticFile,
  useCurrentFrame, useVideoConfig,
} from "remotion";

type Card = { start_frame: number; duration_frames: number; title: string; subtitle: string };
export type TimelineManifest = {
  schema: "short-drama.timeline/v1";
  episode_id: string;
  title: string;
  technical_test: boolean;
  fps: number;
  width: number;
  height: number;
  duration_frames: number;
  intro: Card;
  outro: Card;
  shots: Array<{
    shot_id: string;
    scene_id: string;
    start_frame: number;
    duration_frames: number;
    media: { kind: "image" | "video"; path: string; sha256: string; source_start_frame: number };
    transition: { kind: "fade" | "cut"; duration_frames: number };
  }>;
  tracks: Array<{
    id: string;
    path: string;
    kind: string;
    start_frame: number;
    duration_frames: number;
    source_start_frame: number;
    volume: number;
  }>;
  subtitles: Array<{
    id: string;
    shot_id: string;
    character_id?: string | null;
    text: string;
    start_frame: number;
    end_frame: number;
  }>;
  safe_area: { x: number; y: number; width: number; height: number };
};

export type ProductionEpisodeProps = { timeline: TimelineManifest };

// Render helper stages local files as relative public/media paths. Browser
// consumers never resolve arbitrary remote or file:// paths from the manifest.
const mediaSource = (path: string): string => {
  if (!/^media\/[a-f0-9]{64}\.[a-z0-9]+$/.test(path)) {
    throw new Error("媒体必须由 tools/render_episode.mjs 本地暂存到 public/media");
  }
  return staticFile(path);
};

const TitleCard: React.FC<{ card: Card; episode: string }> = ({ card, episode }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const progress = Math.min(1, frame / Math.min(12, Math.max(1, card.duration_frames - 1)));
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", textAlign: "center", background: "linear-gradient(150deg,#11192d,#372443)", color: "#fff7e8", padding: width * 0.09 }}>
      <div style={{ opacity: 0.4 + progress * 0.6, transform: `translateY(${(1 - progress) * 24}px)` }}>
        <div style={{ fontSize: width * 0.025, color: "#ffcd8b", letterSpacing: 4 }}>{episode}</div>
        <h1 style={{ fontSize: width * 0.075, lineHeight: 1.3, margin: "38px 0" }}>{card.title}</h1>
        <p style={{ fontSize: width * 0.029, color: "#e5dacf", lineHeight: 1.6 }}>{card.subtitle}</p>
      </div>
    </AbsoluteFill>
  );
};

const Shot: React.FC<{ shot: TimelineManifest["shots"][number] }> = ({ shot }) => {
  const frame = useCurrentFrame();
  const fade = shot.transition.kind === "fade" ? shot.transition.duration_frames : 0;
  const opacity = fade > 0 ? Math.max(0, Math.min(1, frame / fade, (shot.duration_frames - 1 - frame) / fade)) : 1;
  const style: React.CSSProperties = { width: "100%", height: "100%", objectFit: "cover" };
  return (
    <AbsoluteFill style={{ opacity }}>
      {shot.media.kind === "image" ? (
        <Img src={mediaSource(shot.media.path)} style={style} />
      ) : (
        <OffthreadVideo src={mediaSource(shot.media.path)} startFrom={shot.media.source_start_frame} muted style={style} />
      )}
    </AbsoluteFill>
  );
};

const Captions: React.FC<{ timeline: TimelineManifest }> = ({ timeline }) => {
  const frame = useCurrentFrame();
  const lines = timeline.subtitles.filter((line) => line.start_frame <= frame && frame < line.end_frame);
  if (!lines.length) return null;
  const area = timeline.safe_area;
  const length = lines.reduce((sum, line) => sum + line.text.length + (line.character_id?.length ?? 0), 0);
  const fontSize = Math.max(24, Math.min(timeline.width * 0.044, Math.sqrt(area.width * area.height / Math.max(1, length)) * 0.74));
  return (
    <div style={{ position: "absolute", left: area.x, top: area.y, width: area.width, height: area.height, display: "flex", flexDirection: "column", justifyContent: "center", textAlign: "center", color: "white", fontSize, lineHeight: 1.45, fontWeight: 600, textShadow: "0 2px 7px #000, 0 0 3px #000", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
      {lines.map((line) => {
        const enter = Math.min(1, (frame - line.start_frame + 1) / 4);
        return <div key={line.id} style={{ padding: "6px 18px", background: "rgba(0,0,0,0.45)", opacity: enter, transform: `translateY(${(1 - enter) * 8}px)`, borderRadius: 10 }}>{line.text}</div>;
      })}
    </div>
  );
};

export const ProductionEpisode: React.FC<ProductionEpisodeProps> = ({ timeline }) => (
  <AbsoluteFill style={{ backgroundColor: "#090b12", fontFamily: '"Noto Sans CJK SC", "Microsoft YaHei", sans-serif' }}>
    {timeline.intro.duration_frames > 0 && (
      <Sequence from={timeline.intro.start_frame} durationInFrames={timeline.intro.duration_frames} name="片头">
        <TitleCard card={timeline.intro} episode={timeline.episode_id} />
      </Sequence>
    )}
    {timeline.shots.map((shot) => (
      <Sequence key={shot.shot_id} from={shot.start_frame} durationInFrames={shot.duration_frames} name={shot.shot_id}>
        <Shot shot={shot} />
      </Sequence>
    ))}
    {timeline.outro.duration_frames > 0 && (
      <Sequence from={timeline.outro.start_frame} durationInFrames={timeline.outro.duration_frames} name="片尾">
        <TitleCard card={timeline.outro} episode={timeline.episode_id} />
      </Sequence>
    )}
    {timeline.tracks.map((track) => (
      <Sequence key={track.id} from={track.start_frame} durationInFrames={track.duration_frames} name={`${track.kind}:${track.id}`} layout="none">
        <Audio src={mediaSource(track.path)} startFrom={track.source_start_frame} volume={track.volume} />
      </Sequence>
    ))}
    <Captions timeline={timeline} />
    {timeline.technical_test && (
      <div style={{ position: "absolute", top: timeline.height * 0.05, left: timeline.width * 0.08, padding: "8px 14px", fontSize: timeline.width * 0.023, color: "#ffe0ad", background: "rgba(0,0,0,.5)", borderRadius: 8 }}>技术测试 · 本地占位素材</div>
    )}
  </AbsoluteFill>
);

export const defaultTimeline: TimelineManifest = {
  schema: "short-drama.timeline/v1", episode_id: "EP000", title: "数据驱动短剧合成", technical_test: true,
  fps: 30, width: 1080, height: 1920, duration_frames: 90,
  intro: { start_frame: 0, duration_frames: 90, title: "数据驱动短剧合成", subtitle: "请通过 render_episode.mjs 加载制作时间线" },
  outro: { start_frame: 90, duration_frames: 0, title: "", subtitle: "" },
  shots: [], tracks: [], subtitles: [], safe_area: { x: 86, y: 1306, width: 908, height: 307 },
};
