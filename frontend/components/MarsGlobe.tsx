"use client";
/* The 3D Mars globe. CesiumJS is loaded from /cesium (copied from node_modules at install time)
   and configured for Mars: nothing here may rely on Cesium's Earth (WGS84) defaults.

   - Ellipsoid: sphere r = 3,396,190 m. Mars Trek tiles, MOLA MEGDR and the CTX DTM are all
     referenced to this IAU 2000 sphere with planetocentric latitude, so a sphere (not Cesium's
     biaxial Ellipsoid.MARS) is what keeps imagery, routes and picks mutually consistent.
   - Tiling: geographic (plate carree), 2 x 1 tiles at level 0, rows counted from the north. */
import { useEffect, useRef, useState } from "react";
import { API_BASE, apiGet } from "@/lib/api";
import { PROFILE_COLORS, useStore } from "@/lib/store";
import type { Layer, Target } from "@/lib/types";

/* eslint-disable @typescript-eslint/no-explicit-any */
declare global { interface Window { Cesium: any; CESIUM_BASE_URL: string } }

export const MARS_RADIUS = 3396190;
let cesiumPromise: Promise<any> | null = null;
let baseMarkers: Promise<[Target[], LandingSite[]]> | null = null;   // curated targets + landing sites, fetched once per page load

function loadCesium(): Promise<any> {
  if (typeof window === "undefined") return Promise.reject(new Error("no window"));
  if (window.Cesium) return Promise.resolve(window.Cesium);
  if (!cesiumPromise) {
    cesiumPromise = new Promise((resolve, reject) => {
      window.CESIUM_BASE_URL = "/cesium/";
      const css = document.createElement("link");
      css.rel = "stylesheet"; css.href = "/cesium/Widgets/widgets.css";
      document.head.appendChild(css);
      const s = document.createElement("script");
      s.src = "/cesium/Cesium.js"; s.async = true;
      s.onload = () => resolve(window.Cesium);
      s.onerror = () => reject(new Error("Cesium runtime could not be loaded from /cesium (run `npm run dev` or `node scripts/copy-cesium.mjs`)."));
      document.head.appendChild(s);
    });
  }
  return cesiumPromise;
}

type RoverData = { rovers: Record<string, { name: string; latest_sol: number; traverse: number[][]; latest: { lon: number; lat: number; sol: number } }> };
type LandingSite = { name: string; lon: number; lat: number; description?: string };

export default function MarsGlobe() {
  const el = useRef<HTMLDivElement>(null);
  const ctx = useRef<{ C: any; viewer: any; mars: any; imagery: Map<string, any>; ds: Record<string, any>; overlayLayer: any; hydrous: any; overlayKey: string } | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const layerDefs = useStore((s) => s.layerDefs);
  const layers = useStore((s) => s.layers);
  const plan = useStore((s) => s.plan);
  const selectedProfile = useStore((s) => s.selectedProfile);
  const showAll = useStore((s) => s.showAllCandidates);
  const targets = useStore((s) => s.targets);
  const missionTargets = useStore((s) => s.missionTargets);
  const selected = useStore((s) => s.selected);
  const habitat = useStore((s) => s.habitat);
  const start = useStore((s) => s.start);
  const goal = useStore((s) => s.goal);
  const flyTo = useStore((s) => s.flyTo);
  const sceneMode = useStore((s) => s.sceneMode);
  const overlay = useStore((s) => s.overlay);
  const sim = useStore((s) => s.sim);
  const simIndex = useStore((s) => s.simIndex);
  const pickMode = useStore((s) => s.pickMode);

  // ---- create the viewer once
  useEffect(() => {
    let destroyed = false;
    let handler: any;
    loadCesium().then((C) => {
      if (destroyed || !el.current) return;
      const mars = new C.Ellipsoid(MARS_RADIUS, MARS_RADIUS, MARS_RADIUS);
      C.Ellipsoid.default = mars;                       // every fromDegrees()/Cartographic call now uses Mars
      C.Ion.defaultAccessToken = undefined;             // no Cesium ion (Earth) services are used
      const viewer = new C.Viewer(el.current, {
        globe: new C.Globe(mars),
        mapProjection: new C.GeographicProjection(mars),
        terrainProvider: new C.EllipsoidTerrainProvider({ ellipsoid: mars }),
        baseLayer: false, baseLayerPicker: false, geocoder: false, timeline: false, animation: false, homeButton: false,
        sceneModePicker: false, navigationHelpButton: false, fullscreenButton: false, infoBox: false, selectionIndicator: false,
        skyAtmosphere: false, requestRenderMode: true, maximumRenderTimeChange: Infinity,
      });
      const scene = viewer.scene;
      scene.globe.baseColor = C.Color.fromCssColorString("#1a0f0b");
      scene.globe.showGroundAtmosphere = false;         // Cesium's ground atmosphere is tuned for Earth's blue sky
      scene.globe.enableLighting = false;
      scene.fog.enabled = false;
      scene.backgroundColor = C.Color.fromCssColorString("#05070d");
      if (scene.moon) scene.moon.show = false;
      if (scene.sun) scene.sun.show = false;
      scene.screenSpaceCameraController.minimumZoomDistance = 120;
      scene.screenSpaceCameraController.maximumZoomDistance = 4.0e7;
      viewer.camera.setView({ destination: C.Cartesian3.fromDegrees(77.45, 12, 1.15e7) });

      const ds: Record<string, any> = {};
      for (const name of ["rovers", "targets", "routes", "markers", "sim"]) {
        ds[name] = new C.CustomDataSource(name);
        viewer.dataSources.add(ds[name]);
      }
      const hydrous = scene.primitives.add(new C.PointPrimitiveCollection());
      hydrous.show = false;
      ctx.current = { C, viewer, mars, imagery: new Map(), ds, overlayLayer: null, hydrous, overlayKey: "" };

      // picking + cursor readout (written straight to the DOM to avoid re-rendering React on every mouse move)
      handler = new C.ScreenSpaceEventHandler(scene.canvas);
      const toLonLat = (pos: any) => {
        const cart = viewer.camera.pickEllipsoid(pos, mars);
        if (!cart) return null;
        const c = C.Cartographic.fromCartesian(cart, mars);
        return { lon: C.Math.toDegrees(c.longitude), lat: C.Math.toDegrees(c.latitude) };
      };
      handler.setInputAction((m: any) => {
        const picked = scene.pick(m.position);
        const id = picked?.id;
        if (id?.marsx?.kind === "target") { useStore.getState().pick({ lon: id.marsx.lon, lat: id.marsx.lat, name: id.marsx.name }); return; }
        const p = toLonLat(m.position);
        if (p) useStore.getState().pick(p);
      }, C.ScreenSpaceEventType.LEFT_CLICK);
      const readout = document.getElementById("cursor-readout");
      handler.setInputAction((m: any) => {
        if (!readout) return;
        const p = toLonLat(m.endPosition);
        readout.textContent = p ? `${Math.abs(p.lat).toFixed(4)}°${p.lat >= 0 ? "N" : "S"}  ${Math.abs(p.lon).toFixed(4)}°${p.lon >= 0 ? "E" : "W"}` : "off globe";
      }, C.ScreenSpaceEventType.MOUSE_MOVE);
      const alt = document.getElementById("camera-altitude");
      viewer.camera.changed.addEventListener(() => {
        if (!alt) return;
        const h = viewer.camera.positionCartographic.height;
        alt.textContent = h > 1e6 ? `${(h / 1000).toFixed(0)} km` : h > 1e4 ? `${(h / 1000).toFixed(1)} km` : `${h.toFixed(0)} m`;
      });
      viewer.camera.percentageChanged = 0.05;
      setReady(true);
    }).catch((e) => setError(String(e.message || e)));
    return () => {
      destroyed = true;
      handler?.destroy();
      if (ctx.current) { ctx.current.viewer.destroy(); ctx.current = null; }
    };
  }, []);

  // ---- imagery layers (NASA Mars Trek WMTS)
  useEffect(() => {
    const c = ctx.current;
    if (!ready || !c) return;
    const { C, viewer, mars } = c;
    const wmts = layerDefs.filter((l) => l.kind === "wmts");
    let index = 0;
    for (const def of wmts) {
      const st = layers[def.id];
      let lyr = c.imagery.get(def.id);
      if (st?.visible) {
        if (!lyr) {
          lyr = viewer.imageryLayers.addImageryProvider(makeProvider(C, mars, def), index);
          c.imagery.set(def.id, lyr);
        }
        lyr.alpha = st.opacity;
        index++;
      } else if (lyr) {
        viewer.imageryLayers.remove(lyr, true);
        c.imagery.delete(def.id);
      }
    }
    viewer.scene.requestRender();
  }, [ready, layerDefs, layers]);

  // ---- computed overlay (slope / hazard / quality) for the analysis region
  useEffect(() => {
    const c = ctx.current;
    if (!ready || !c) return;
    const { C, viewer } = c;
    const want = (["mx_slope", "mx_hazard", "mx_quality"] as const).find((id) => layers[id]?.visible);
    const kind = want ? { mx_slope: "slope", mx_hazard: "hazard", mx_quality: "quality" }[want] : null;
    const key = overlay && kind ? `${kind}|${overlay.bbox.join(",")}` : "";
    if (key === c.overlayKey) { if (c.overlayLayer && want) c.overlayLayer.alpha = layers[want].opacity; viewer.scene.requestRender(); return; }
    if (c.overlayLayer) { viewer.imageryLayers.remove(c.overlayLayer, true); c.overlayLayer = null; }
    c.overlayKey = key;
    if (!overlay || !kind || !want) { viewer.scene.requestRender(); return; }
    const [w, s, e, n] = overlay.bbox;
    const url = API_BASE + overlay.url.replace(/kind=[a-z]+/, `kind=${kind}`);
    C.SingleTileImageryProvider.fromUrl(url, { rectangle: C.Rectangle.fromDegrees(w, s, e, n) }).then((prov: any) => {
      if (!ctx.current || ctx.current.overlayKey !== key) return;
      c.overlayLayer = viewer.imageryLayers.addImageryProvider(prov);
      c.overlayLayer.alpha = layers[want].opacity;
      c.overlayLayer.magnificationFilter = C.TextureMagnificationFilter.NEAREST;
      viewer.scene.requestRender();
    }).catch(() => { c.overlayKey = ""; });
  }, [ready, overlay, layers]);

  // ---- hydrous mineral detections (CRISM / OMEGA)
  useEffect(() => {
    const c = ctx.current;
    if (!ready || !c) return;
    const on = !!layers["mx_minerals"]?.visible;
    c.hydrous.show = on;
    if (on && c.hydrous.length === 0) {
      apiGet<{ detections: [number, number, string][] }>("/api/v1/science/hydrous").then(({ data }) => {
        if (!ctx.current) return;
        const { C } = c;
        for (const [lon, lat, inst] of data.detections) {
          c.hydrous.add({ position: C.Cartesian3.fromDegrees(lon, lat, 200), pixelSize: 5,
            color: C.Color.fromCssColorString(inst === "CRISM" ? "#5ee0d0" : "#d6a2ff").withAlpha(0.9), outlineColor: C.Color.BLACK.withAlpha(0.6), outlineWidth: 1 });
        }
        c.viewer.scene.requestRender();
      }).catch(() => {});
    }
    c.viewer.scene.requestRender();
  }, [ready, layers]);

  // ---- rovers + landing sites
  useEffect(() => {
    const c = ctx.current;
    if (!ready || !c) return;
    const { C, ds } = c;
    ds.rovers.show = !!layers["mx_rovers"]?.visible;
    if (ds.rovers.show && ds.rovers.entities.values.length === 0) {
      apiGet<RoverData>("/api/v1/planet/rovers").then(({ data }) => {
        if (!ctx.current || ds.rovers.entities.values.length) return;
        for (const [key, r] of Object.entries(data.rovers)) {
          const col = C.Color.fromCssColorString(key === "perseverance" ? "#ffd166" : "#ff8fa3");
          ds.rovers.entities.add({ polyline: { positions: C.Cartesian3.fromDegreesArray(r.traverse.flat()), width: 2, material: col.withAlpha(0.85) } });
          ds.rovers.entities.add({ position: C.Cartesian3.fromDegrees(r.latest.lon, r.latest.lat),
            point: { pixelSize: 9, color: col, outlineColor: C.Color.BLACK, outlineWidth: 2 },
            label: label(C, `${r.name.split(" (")[0]} · sol ${r.latest.sol}`, col) });
        }
        c.viewer.scene.requestRender();
      }).catch(() => {});
    }
    c.viewer.scene.requestRender();
  }, [ready, layers]);

  // ---- science targets + landing sites + mission targets
  useEffect(() => {
    const c = ctx.current;
    if (!ready || !c) return;
    const { C, ds } = c;
    let cancelled = false;
    ds.targets.show = !!layers["mx_targets"]?.visible;
    const draw = (base: Target[], sites: LandingSite[]) => {
      if (cancelled) return;
      ds.targets.entities.removeAll();
      const mission = new Set(missionTargets.map((t) => t.id));
      const seen = new Set<string>();
      for (const t of [...missionTargets, ...targets, ...base]) {
        if (seen.has(t.id)) continue;
        seen.add(t.id);
        const inMission = mission.has(t.id);
        const col = C.Color.fromCssColorString(inMission ? "#ffffff" : t.kind === "mineral_detection" ? "#5ee0d0" : t.kind === "rover_waypoint" ? "#ffd166" : t.kind === "gazetteer" ? "#9db4d6" : "#e2603a");
        // dense local results (waypoints, detections, named features) only label when zoomed in, with short text
        const minor = !inMission && (t.kind === "rover_waypoint" || t.kind === "mineral_detection" || t.kind === "gazetteer");
        const text = t.kind === "rover_waypoint" ? (t.name.match(/sol d+/)?.[0] ?? t.name) : t.kind === "mineral_detection" ? t.name.split(" ")[0] : (() => { const n = t.name.replace(/s*((rover position|crater floor)[^)]*)/, ""); return n.length > 40 ? n.slice(0, 38) + "…" : n; })();
        const e = ds.targets.entities.add({ position: C.Cartesian3.fromDegrees(t.lon, t.lat),
          point: { pixelSize: inMission ? 11 : minor ? 6 : 8, color: col, outlineColor: C.Color.fromCssColorString(inMission ? "#e2603a" : "#000"), outlineWidth: inMission ? 3 : 1.5 },
          label: label(C, text, col, minor ? (t.kind === "gazetteer" ? 1.5e6 : 2.5e4) : 2.5e6) });
        e.marsx = { kind: "target", lon: t.lon, lat: t.lat, name: t.name };
      }
      for (const s of sites) {
        const e = ds.targets.entities.add({ position: C.Cartesian3.fromDegrees(s.lon, s.lat),
          point: { pixelSize: 7, color: C.Color.fromCssColorString("#3b9eff"), outlineColor: C.Color.WHITE, outlineWidth: 1.5 },
          label: label(C, s.name.split(" - ")[0].replace(" landing site", ""), C.Color.fromCssColorString("#8cc6ff"), 1.2e7) });
        e.marsx = { kind: "target", lon: s.lon, lat: s.lat, name: s.name };
      }
      c.viewer.scene.requestRender();
    };
    baseMarkers ??= Promise.all([
      apiGet<{ targets: Target[] }>("/api/v1/science/targets?limit=40").then((r) => r.data.targets),
      apiGet<{ results: LandingSite[] }>("/api/v1/planet/locations?kind=landing_site&limit=50").then((r) => r.data.results),
    ]);
    baseMarkers.then(([base, sites]) => draw(base, sites)).catch(() => { baseMarkers = null; draw([], []); });
    return () => { cancelled = true; };
  }, [ready, layers, targets, missionTargets]);

  // ---- routes
  useEffect(() => {
    const c = ctx.current;
    if (!ready || !c) return;
    const { C, ds } = c;
    ds.routes.entities.removeAll();
    ds.routes.show = !!layers["mx_routes"]?.visible;
    if (plan) {
      const line = (coords: number[][]) => C.Cartesian3.fromDegreesArray(coords.flatMap((p) => [p[0], p[1]]));
      for (const cand of plan.candidates) {
        const sel = cand.profile === selectedProfile;
        if (!sel && (!showAll || cand.identical_to)) continue;
        const col = C.Color.fromCssColorString(PROFILE_COLORS[cand.profile] || "#fff");
        ds.routes.entities.add({ polyline: { positions: line(cand.geometry.coordinates), width: sel ? 5 : 2.5,
          material: sel ? new C.PolylineOutlineMaterialProperty({ color: col, outlineColor: C.Color.BLACK.withAlpha(0.7), outlineWidth: 2 }) : col.withAlpha(0.55) } });
      }
      if (plan.return_route) {
        ds.routes.entities.add({ polyline: { positions: line(plan.return_route.geometry.coordinates), width: 3,
          material: new C.PolylineDashMaterialProperty({ color: C.Color.fromCssColorString(PROFILE_COLORS.return), dashLength: 14 }) } });
      }
    }
    c.viewer.scene.requestRender();
  }, [ready, plan, selectedProfile, showAll, layers]);

  // ---- user markers (selection, habitat, start, goal)
  useEffect(() => {
    const c = ctx.current;
    if (!ready || !c) return;
    const { C, ds } = c;
    ds.markers.entities.removeAll();
    const mark = (p: { lon: number; lat: number } | null, text: string, css: string, size: number) => {
      if (!p) return;
      const col = C.Color.fromCssColorString(css);
      ds.markers.entities.add({ position: C.Cartesian3.fromDegrees(p.lon, p.lat),
        point: { pixelSize: size, color: col.withAlpha(0.25), outlineColor: col, outlineWidth: 2.5 }, label: label(C, text, col) });
    };
    mark(selected, "", "#ffffff", 13);
    mark(habitat, "HABITAT", "#3b9eff", 15);
    mark(start, "START", "#3ecf8e", 12);
    mark(goal, "DESTINATION", "#e2603a", 12);
    c.viewer.scene.requestRender();
  }, [ready, selected, habitat, start, goal]);

  // ---- simulation marker
  useEffect(() => {
    const c = ctx.current;
    if (!ready || !c) return;
    const { C, ds } = c;
    ds.sim.entities.removeAll();
    if (sim && sim.frames.length) {
      const f = sim.frames[Math.min(simIndex, sim.frames.length - 1)];
      const done = sim.frames.slice(0, simIndex + 1).flatMap((x) => [x.lon, x.lat]);
      if (done.length >= 4) ds.sim.entities.add({ polyline: { positions: C.Cartesian3.fromDegreesArray(done), width: 4, material: C.Color.WHITE.withAlpha(0.9) } });
      const col = C.Color.fromCssColorString(f.phase.includes("emergency") ? "#ef5350" : "#ffffff");
      ds.sim.entities.add({ position: C.Cartesian3.fromDegrees(f.lon, f.lat),
        point: { pixelSize: 14, color: col, outlineColor: C.Color.fromCssColorString("#e2603a"), outlineWidth: 4 },
        label: label(C, `SIMULATED CREW · ${f.energy_pct}%`, C.Color.fromCssColorString("#ffd0a8")) });
    }
    c.viewer.scene.requestRender();
  }, [ready, sim, simIndex]);

  // ---- camera commands
  useEffect(() => {
    const c = ctx.current;
    if (!ready || !c || !flyTo) return;
    const h = flyTo.height ?? Math.min(Math.max(c.viewer.camera.positionCartographic.height, 6000), 60000);
    c.viewer.camera.flyTo({ destination: c.C.Cartesian3.fromDegrees(flyTo.lon, flyTo.lat, h), duration: 1.6 });
  }, [ready, flyTo]);

  useEffect(() => {
    const c = ctx.current;
    if (!ready || !c) return;
    const { C, viewer } = c;
    if (sceneMode === "2D" && viewer.scene.mode !== C.SceneMode.SCENE2D) viewer.scene.morphTo2D(0.8);
    if (sceneMode === "3D" && viewer.scene.mode !== C.SceneMode.SCENE3D) viewer.scene.morphTo3D(0.8);
  }, [ready, sceneMode]);

  return (
    <div className="absolute inset-0">
      <div ref={el} className="absolute inset-0" style={{ cursor: pickMode ? "crosshair" : "grab" }} />
      {!ready && !error && (
        <div className="absolute inset-0 grid place-items-center text-dim">
          <div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-mars pulse" /> Loading Mars globe…</div>
        </div>
      )}
      {error && <div className="absolute inset-0 grid place-items-center p-8 text-center text-danger">3D globe unavailable: {error}</div>}
    </div>
  );
}

function makeProvider(C: any, mars: any, def: Layer) {
  const b = def.bbox || [-180, -90, 180, 90];
  return new C.UrlTemplateImageryProvider({
    url: def.tile_url,
    tilingScheme: new C.GeographicTilingScheme({ ellipsoid: mars, numberOfLevelZeroTilesX: 2, numberOfLevelZeroTilesY: 1 }),
    maximumLevel: def.max_level,
    rectangle: C.Rectangle.fromDegrees(Math.max(-180, b[0]), Math.max(-90, b[1]), Math.min(180, b[2]), Math.min(90, b[3])),
    credit: new C.Credit(def.attribution, false),
  });
}

function label(C: any, text: string, color: any, far = 6e6) {
  return {
    text, font: "600 11px ui-sans-serif, system-ui, sans-serif", fillColor: color, outlineColor: C.Color.BLACK, outlineWidth: 3,
    style: C.LabelStyle.FILL_AND_OUTLINE, pixelOffset: new C.Cartesian2(10, -10), horizontalOrigin: C.HorizontalOrigin.LEFT,
    distanceDisplayCondition: new C.DistanceDisplayCondition(0, far), showBackground: false,
  };
}
