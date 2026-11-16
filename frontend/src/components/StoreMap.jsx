import { useEffect, useMemo, useRef, useState } from "react";
import {
  GeolocateControl,
  LngLatBounds,
  Map as MapLibreMap,
  NavigationControl,
  setWorkerUrl,
} from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import "./StoreMap.css";

setWorkerUrl(workerUrl);

const STORES_URL = "https://agora-72bb.onrender.com/stores/all";
const CHAINS = [
  { key: "new_world", label: "New World", color: "#c02638" },
  { key: "woolworths", label: "Woolworths", color: "#207346" },
  { key: "paknsave", label: "PAK’nSAVE", color: "#a36200" },
];

const SOURCE = "agora-stores";
const CLUSTERS = "agora-store-clusters";
const POINTS = "agora-store-points";
const INDIVIDUAL_STORES = ["!", ["has", "point_count"]];
const EMPTY_GEOJSON = { type: "FeatureCollection", features: [] };

export default function StoreMap({
  storesUrl = STORES_URL,
  searchQuery = "",
  onSelectStore,
  onRemoveStore,
  addedStoreKeys,
}) {
  const [storesByChain, setStoresByChain] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    setStoresByChain(null);
    setError(null);

    async function loadStores() {
      try {
        const response = await fetch(storesUrl, { signal: controller.signal });
        if (!response.ok) {
          throw new Error(`Could not load stores (HTTP ${response.status}).`);
        }

        const stores = await response.json();
        if (
          !Array.isArray(stores?.new_world) ||
          !Array.isArray(stores?.woolworths) ||
          !Array.isArray(stores?.paknsave)
        ) {
          throw new Error("The server returned an unexpected stores response.");
        }

        if (!controller.signal.aborted) setStoresByChain(stores);
      } catch (error) {
        if (!controller.signal.aborted) {
          setError(error instanceof TypeError ? "Could not load stores." : error.message);
        }
      }
    }

    loadStores();
    return () => controller.abort();
  }, [storesUrl]);

  if (error) return <p role="alert">{error}</p>;
  if (!storesByChain) return <p role="status">Loading stores…</p>;

  return (
    <StoreMapView
      storesByChain={storesByChain}
      searchQuery={searchQuery}
      onSelectStore={onSelectStore}
      onRemoveStore={onRemoveStore}
      addedStoreKeys={addedStoreKeys}
    />
  );
}

function normalizeSearchText(text) {
  return text.normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/['‘’ʼ]/g, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function storeMatchesSearch(store, chainLabel, terms) {
  if (!terms.length) return true;

  const locationFields = [store, store.address].flatMap((location) => {
    const postcode = location?.postcode ?? location?.postCode
      ?? location?.postalCode ?? location?.postal_code;

    return [
      location?.addressLine1, location?.addressLine2, location?.formattedAddress,
      location?.street, location?.suburb, location?.locality, location?.city,
      location?.town, location?.region,
      typeof postcode === "number" ? String(postcode).padStart(4, "0") : postcode,
    ];
  });
  const searchableText = normalizeSearchText(
    [chainLabel, store.name, store.address, ...locationFields]
      .filter((value) => typeof value === "string")
      .join(" "),
  );

  return terms.every((term) => searchableText.includes(term));
}

function buildStoreData(storesByChain, searchQuery) {
  const byKey = new Map();
  const countsByChain = {};
  const features = [];
  const bounds = new LngLatBounds();
  const terms = normalizeSearchText(searchQuery).split(" ").filter(Boolean);

  for (const chain of CHAINS) {
    countsByChain[chain.key] = 0;
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
      if (!storeMatchesSearch(store, chain.label, terms)) continue;

      const key = `${chain.key}:${id}`;
      const coordinates = [longitude, latitude];
      const name = (typeof store.name === "string" && store.name.trim()) || chain.label;
      const address = [store.address, store.address?.formattedAddress, store.address?.addressLine1]
        .find((value) => typeof value === "string" && value.trim()) ?? "";
      byKey.set(key, { chain: chain.key, store, name, address });
      countsByChain[chain.key] += 1;
      bounds.extend(coordinates);
      features.push({
        type: "Feature",
        id: key,
        geometry: { type: "Point", coordinates },
        properties: {
          key,
          color: chain.color,
          name,
        },
      });
    }
  }

  return {
    byKey, bounds, countsByChain, isSearching: terms.length > 0,
    geojson: { type: "FeatureCollection", features },
  };
}

function StoreMapView({ storesByChain, searchQuery, onSelectStore, onRemoveStore, addedStoreKeys }) {
  const containerRef = useRef(null);
  const legendRef = useRef(null);
  const detailsRef = useRef(null);
  const resultsRef = useRef(null);
  const mapRef = useRef(null);
  const [status, setStatus] = useState("loading");
  const [selection, setSelection] = useState(null);
  const storeData = useMemo(
    () => buildStoreData(storesByChain, searchQuery),
    [storesByChain, searchQuery],
  );
  const { byKey, countsByChain, isSearching } = storeData;
  const activeKey = selection?.data === storeData ? selection.key : null;
  const active = byKey.get(activeKey);
  const activeIsAdded = addedStoreKeys?.has(activeKey) ?? false;

  function closeStoreDetails() {
    setSelection(null);
    const focusTarget = resultsRef.current ?? mapRef.current?.getCanvas();
    focusTarget?.focus({ preventScroll: true });
  }

  function selectSearchResult(event) {
    const key = event.target.value;
    setSelection(byKey.has(key) ? { key, data: storeData, focusResult: true } : null);
  }

  useEffect(() => {
    let map;
    try {
      map = new MapLibreMap({
        container: containerRef.current,
        style: "https://tiles.openfreemap.org/styles/liberty",
        center: [173, -41],
        zoom: 4.5,
        scrollZoom: true,
        fadeDuration: 0,
        attributionControl: {
          compact: false,
          customAttribution: '<a href="https://maplibre.org/" target="_blank">MapLibre</a>',
        },
        locale: { "GeolocateControl.FindMyLocation": "Use my location" },
      });
    } catch {
      setStatus("error");
      return;
    }

    mapRef.current = map;

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
          "circle-radius": ["step", ["get", "point_count"], 14, 20, 17, 60, 21],
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
        filter: INDIVIDUAL_STORES,
        paint: {
          "circle-color": ["get", "color"],
          "circle-radius": 7,
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });
      map.addLayer({
        id: "agora-store-labels",
        type: "symbol",
        source: SOURCE,
        filter: INDIVIDUAL_STORES,
        layout: {
          "text-field": ["get", "name"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 12,
          "text-anchor": "top",
          "text-offset": [0, 0.85],
          "text-allow-overlap": true,
        },
        paint: {
          "text-color": "#20362b",
          "text-halo-color": "#fff",
          "text-halo-width": 1.5,
        },
      });

      for (const layer of [CLUSTERS, POINTS]) {
        map.on("mouseenter", layer, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layer, () => {
          map.getCanvas().style.cursor = "";
        });
      }

      map.addControl(
        new GeolocateControl({
          fitBoundsOptions: { maxZoom: 13 },
          trackUserLocation: false,
        }),
        "top-right",
      );
      map.addControl(new NavigationControl({ showCompass: false }), "top-right");
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

    const { geojson, bounds } = storeData;
    let current = true;

    async function expandCluster({ features }) {
      const cluster = features[0];
      try {
        const zoom = await source.getClusterExpansionZoom(cluster.properties.cluster_id);
        if (current && mapRef.current === map) {
          setSelection(null);
          map.easeTo({ center: cluster.geometry.coordinates, zoom });
        }
      } catch (error) {
        if (current && mapRef.current === map) {
          console.warn("Could not zoom to the store cluster.", error);
        }
      }
    }

    function selectPin({ features }) {
      setSelection({ key: features[0].properties.key, data: storeData });
    }

    map.on("click", CLUSTERS, expandCluster);
    map.on("click", POINTS, selectPin);
    source.setData(geojson);
    if (!bounds.isEmpty()) {
      const canvas = containerRef.current.getBoundingClientRect();
      const legend = legendRef.current.getBoundingClientRect();
      const details = detailsRef.current.getBoundingClientRect();

      map.fitBounds(bounds, {
        padding: {
          top: Math.max(34, legend.bottom - canvas.top + 14),
          right: 64,
          bottom: Math.max(44, canvas.bottom - details.top + 44),
          left: 64,
        },
        maxZoom: 13,
        duration: 0,
      });
    }

    return () => {
      current = false;
      map.off("click", CLUSTERS, expandCluster);
      map.off("click", POINTS, selectPin);
    };
  }, [status, storeData]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !active || !selection?.focusResult) return;

    const canvas = containerRef.current.getBoundingClientRect();
    const legend = legendRef.current.getBoundingClientRect();
    const details = detailsRef.current.getBoundingClientRect();
    const top = Math.max(canvas.top, legend.bottom) + 12;
    const bottom = Math.max(top, Math.min(canvas.bottom, details.top) - 30);
    const { longitude, latitude } = active.store;

    map.easeTo({
      center: [longitude, latitude],
      zoom: Math.max(map.getZoom(), 15),
      offset: [0, (top + bottom - canvas.top - canvas.bottom) / 2],
    });
  }, [active, selection]);

  const searchStatus = byKey.size === 0
    ? "No supermarkets match this search."
    : `${byKey.size} ${byKey.size === 1 ? "supermarket" : "supermarkets"} found.`;

  return (
    <section className="agora-store-map" aria-label="Store map">
      <ul className="agora-store-map__legend" aria-label="Store chains" ref={legendRef}>
        {CHAINS.map(({ key, label, color }) => {
          const count = countsByChain[key];
          return (
            <li key={key}>
              <span
                className="agora-store-map__legend-swatch"
                aria-hidden="true"
                style={{ backgroundColor: color }}
              />
              <div>
                {label}
                <small>{`${count} ${count === 1 ? "store" : "stores"}`}</small>
              </div>
            </li>
          );
        })}
      </ul>
      <div className="agora-store-map__canvas" ref={containerRef} />
      <div className="agora-store-map__details" ref={detailsRef}>
        <div className="agora-store-map__detail-info">
          <div role="status">
            {status === "loading" && <p>Loading map…</p>}
            {status === "error" && <p>The map couldn’t load.</p>}
            {status === "ready" && active && (
              <>
                <strong>{active.name}</strong>
                {active.address && <p>{active.address}</p>}
              </>
            )}
            {status === "ready" && !active && (
              <p>
                {isSearching ? searchStatus : (
                  byKey.size ? "Choose a pin to see store details." : "No store locations to show."
                )}
              </p>
            )}
          </div>
          {status === "ready" && isSearching && byKey.size > 0 && (
            <select
              className="agora-store-map__search-results"
              aria-label="Matching supermarkets"
              ref={resultsRef}
              value={activeKey ?? ""}
              onChange={selectSearchResult}
            >
              <option value="">Choose a supermarket</option>
              {Array.from(byKey, ([key, { name, address }]) => (
                <option key={key} value={key}>
                  {address ? `${name} · ${address}` : name}
                </option>
              ))}
            </select>
          )}
        </div>
        {status === "ready" && active && (
          <div className="agora-store-map__detail-actions">
            <button
              type="button"
              className="button secondary"
              aria-label="Close store details"
              onClick={closeStoreDetails}
            >
              Close
            </button>
            {activeIsAdded && onRemoveStore ? (
              <button
                type="button"
                className="agora-store-map__remove-button"
                onClick={() => onRemoveStore(activeKey)}
              >
                Remove supermarket
              </button>
            ) : onSelectStore && (
              <button
                type="button"
                aria-disabled={activeIsAdded}
                onClick={() => {
                  if (!activeIsAdded) onSelectStore(active.chain, active.store, activeKey);
                }}
              >
                {activeIsAdded ? "Added" : "Add supermarket"}
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
