import React from "react";
import { Composition } from "remotion";
import { ShortDramaPreview, type ShortDramaPreviewProps } from "./ShortDramaPreview";
import { ProductionEpisode, defaultTimeline } from "./ProductionEpisode";

const defaultProps: ShortDramaPreviewProps = {
  title: "短剧项目预览",
  subtitle: "第 1 集 · 镜头合成测试",
};

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="ShortDramaPreview"
      component={ShortDramaPreview}
      durationInFrames={180}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={defaultProps}
    />
    <Composition
      id="ProductionEpisode"
      component={ProductionEpisode}
      durationInFrames={defaultTimeline.duration_frames}
      fps={defaultTimeline.fps}
      width={defaultTimeline.width}
      height={defaultTimeline.height}
      defaultProps={{ timeline: defaultTimeline }}
      calculateMetadata={({ props }) => ({
        durationInFrames: props.timeline.duration_frames,
        fps: props.timeline.fps,
        width: props.timeline.width,
        height: props.timeline.height,
      })}
    />
  </>
);
