/**
 * @format
 */

import "react-native";
import ReactTestRenderer from "react-test-renderer";
import App from "../App";

jest.mock("@borndotcom/react-native-godot", () => {
  const React = require("react");
  const { View } = require("react-native");

  return {
    RTNGodot: {
      getInstance: jest.fn(() => null),
      pause: jest.fn(),
      resume: jest.fn(),
    },
    RTNGodotView: (props: object) => React.createElement(View, props),
    runOnGodotThread: jest.fn(() => Promise.resolve({scene: {frames: 3, variant: "a"}, engine: "4.7.2", native: {generation: 1, state: 2}})),
  };
});

jest.mock("expo-file-system/legacy", () => ({
  bundleDirectory: "file:///",
}));

jest.mock("react-native-worklets", () => ({
  scheduleOnRN: (callback: (...args: unknown[]) => void, ...args: unknown[]) => callback(...args),
}));

jest.mock("expo-device", () => ({
  isDevice: false,
}));

test("renders correctly", async () => {
  await ReactTestRenderer.act(() => {
    ReactTestRenderer.create(<App />);
  });
});
