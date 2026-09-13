import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import {
  init,
  use,
  type EChartsCoreOption,
  type EChartsType,
} from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { onBeforeUnmount, onMounted, ref, watchEffect } from "vue";

use([BarChart, LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

export function useEChart(
  buildOption: (reducedMotion: boolean) => EChartsCoreOption,
) {
  const chartElement = ref<HTMLElement | null>(null);
  const reducedMotion = ref(false);
  let chart: EChartsType | null = null;
  let resizeObserver: ResizeObserver | null = null;
  let motionQuery: MediaQueryList | null = null;

  const render = () => {
    chart?.setOption(buildOption(reducedMotion.value), {
      lazyUpdate: true,
      notMerge: true,
    });
  };

  const resize = () => chart?.resize();

  const syncMotionPreference = () => {
    reducedMotion.value = motionQuery?.matches ?? false;
  };

  watchEffect(() => {
    const option = buildOption(reducedMotion.value);
    chart?.setOption(option, { lazyUpdate: true, notMerge: true });
  });

  onMounted(() => {
    if (!chartElement.value) return;
    motionQuery = window.matchMedia?.("(prefers-reduced-motion: reduce)") ?? null;
    syncMotionPreference();
    motionQuery?.addEventListener("change", syncMotionPreference);

    chart = init(chartElement.value, undefined, { renderer: "canvas" });
    render();

    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(chartElement.value);
    } else {
      window.addEventListener("resize", resize);
    }
  });

  onBeforeUnmount(() => {
    resizeObserver?.disconnect();
    window.removeEventListener("resize", resize);
    motionQuery?.removeEventListener("change", syncMotionPreference);
    chart?.dispose();
    chart = null;
  });

  return { chartElement };
}
