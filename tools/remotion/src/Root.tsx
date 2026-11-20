import React from "react";
import {Composition} from "remotion";
import {Figure} from "./SampleFigure";

export const Root: React.FC = () => (
  <Composition
    id="Figure"
    component={Figure}
    durationInFrames={150}
    fps={30}
    width={1920}
    height={1080}
  />
);
