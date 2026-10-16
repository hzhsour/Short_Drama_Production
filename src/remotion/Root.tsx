import React from "react";
import { Composition } from "remotion";
import { ShortDramaPreview, type ShortDramaPreviewProps } from "./ShortDramaPreview";

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
  </>
);
