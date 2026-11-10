import { useEffect, useMemo, useRef, useState } from "react";
import {
  LngLatBounds,
  Map as MapLibreMap,
  NavigationControl,
  setWorkerUrl,
} from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import "./StoreMap.css";

setWorkerUrl(workerUrl);

const CHAINS = [
  { key: "new_world", label: "New World", color: "#c02638" },
  { key: "woolworths", label: "Woolworths", color: "#207346" },
  { key: "paknsave", label: "PAK’nSAVE", color: "#a36200" },
];

const SOURCE = "agora-stores";
const CLUSTERS = "agora-store-clusters";
const POINTS = "agora-store-points";
const EMPTY_GEOJSON = { type: "FeatureCollection", features: [] };

function buildStoreData(storesByChain) {
  const byKey = new Map();
  const features = [];
  const bounds = new LngLatBounds();

  for (const chain of CHAINS) {
    const stores = storesByChain?.[chain.key];
    if (!Array.isArray(stores)) continue;

    for (const store of stores) {
      const id = store?.id ?? store?.store_id;
      const { latitude, longitude } = store ?? {};
      if (
        id == null ||
        !Number.isFinite(latitude) ||
        !Number.isFinite(longitude) ||
        Math.abs(latitude) > 90 ||
        Math.abs(longitude) > 180
      ) {
        continue;
      }

      const key = `${chain.key}:${id}`;
      const coordinates = [longitude, latitude];
      byKey.set(key, { chain: chain.key, store });
      bounds.extend(coordinates);
      features.push({
        type: "Feature",
        id: key,
        geometry: { type: "Point", coordinates },
        properties: { key, color: chain.color },
      });
    }
  }

  return { byKey, bounds, geojson: { type: "FeatureCollection", features } };
}

export default function StoreMap({ storesByChain, onSelectStore }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const [status, setStatus] = useState("loading");
  const [activeKey, setActiveKey] = useState(null);
  const { byKey, bounds, geojson } = useMemo(
    () => buildStoreData(storesByChain),
    [storesByChain],
  );
  const active = byKey.get(activeKey);

  useEffect(() => {
    let map;
    try {
      map = new MapLibreMap({
        container: containerRef.current,
        style: "https://tiles.openfreemap.org/styles/liberty",
        center: [173, -41],
        zoom: 4.5,
        scrollZoom: false,
      });
    } catch {
      setStatus("error");
      return;
    }

    mapRef.current = map;
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");

    function handleInitialError() {
      setStatus("error");
    }

    map.on("error", handleInitialError);
    map.once("load", () => {
      map.off("error", handleInitialError);
      map.addSource(SOURCE, {
        type: "geojson",
        data: EMPTY_GEOJSON,
        cluster: true,
        clusterRadius: 42,
        clusterMaxZoom: 14,
      });

      map.addLayer({
        id: CLUSTERS,
        type: "circle",
        source: SOURCE,
        filter: ["has", "point_count"],
        paint: {
          "circle-color": "#263d56",
          "circle-radius": ["step", ["get", "point_count"], 17, 20, 21, 60, 26],
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });
      map.addLayer({
        id: "agora-store-cluster-counts",
        type: "symbol",
        source: SOURCE,
        filter: ["has", "point_count"],
        layout: {
          "text-field": ["to-string", ["get", "point_count"]],
          "text-font": ["Noto Sans Regular"],
          "text-size": 12,
          "text-allow-overlap": true,
        },
        paint: { "text-color": "#fff" },
      });
      map.addLayer({
        id: POINTS,
        type: "circle",
        source: SOURCE,
        filter: ["!", ["has", "point_count"]],
        paint: {
          "circle-color": ["get", "color"],
          "circle-radius": 7,
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });

      map.on("click", CLUSTERS, async ({ features }) => {
        const cluster = features[0];
        try {
          const zoom = await map.getSource(SOURCE).getClusterExpansionZoom(
            cluster.properties.cluster_id,
          );
          if (mapRef.current === map) {
            setActiveKey(null);
            map.easeTo({ center: cluster.geometry.coordinates, zoom });
          }
        } catch (error) {
          if (mapRef.current === map) {
            console.warn("Could not zoom to the store cluster.", error);
          }
        }
      });

      map.on("click", POINTS, ({ features }) => {
        setActiveKey(features[0].properties.key);
      });

      for (const layer of [CLUSTERS, POINTS]) {
        map.on("mouseenter", layer, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layer, () => {
          map.getCanvas().style.cursor = "";
        });
      }

      setStatus("ready");
    });

    return () => {
      mapRef.current = null;
      map.remove();
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const source = map?.getSource(SOURCE);
    if (status !== "ready" || !source) return;

    source.setData(geojson);
    if (!bounds.isEmpty()) {
      map.fitBounds(bounds, { padding: 34, maxZoom: 13, duration: 0 });
    }
  }, [status, bounds, geojson]);

  return (
    <section className="agora-store-map" aria-label="Supermarket map">
      <ul className="agora-store-map__legend" aria-label="Supermarkets">
        {CHAINS.map(({ key, label, color }) => (
          <li key={key}>
            <span aria-hidden="true" style={{ backgroundColor: color }} />
            {label}
          </li>
        ))}
      </ul>
      <div className="agora-store-map__canvas" ref={containerRef} />
      <div className="agora-store-map__details">
        <div role="status">
          {status === "loading" && <p>Loading map…</p>}
          {status === "error" && <p>The map couldn’t load.</p>}
          {status === "ready" && (
            active ? (
              <>
                <strong>{active.store.name}</strong>
                <p>{active.store.address}</p>
              </>
            ) : (
              <p>
                {byKey.size ? "Choose a pin to see store details." : "No store locations to show."}
              </p>
            )
          )}
        </div>
        {status === "ready" && active && onSelectStore && (
          <button type="button" onClick={() => onSelectStore(active.chain, active.store)}>
            Select store
          </button>
        )}
      </div>
    </section>
  );
}
