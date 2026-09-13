import { describe, expect, it } from "vitest";

import {
  callStateLabel,
  dispatchLabel,
  formatDuration,
  formatNumber,
  taskStatusLabel,
} from "../src/format";

describe("观测数据格式化", () => {
  it("格式化 Token 与耗时", () => {
    expect(formatNumber(12345)).toContain("12");
    expect(formatDuration(480)).toBe("480 ms");
    expect(formatDuration(1500)).toBe("1.5 s");
    expect(formatDuration(null)).toBe("—");
  });

  it("使用稳定的中文状态文案", () => {
    expect(taskStatusLabel("ACCEPTED")).toBe("已完成");
    expect(dispatchLabel("OUTCOME_UNKNOWN")).toBe("结果未知");
    expect(callStateLabel("TIMED_OUT")).toBe("请求超时");
  });
});
