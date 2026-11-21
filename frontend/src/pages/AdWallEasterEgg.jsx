import { useEffect, useRef, useState } from "react";

const banners = [
  ["90aa5732ff6a0605dea4bc7619bc1c8b", 728, 90],
  ["b527ac16362abe37ce9c761f49ccc7e3", 468, 60],
  ["23ba3388fc9ab468c38e5eefb3f9668e", 300, 250],
  ["44c61b118ad9241eba88f23b66e5f69a", 160, 300],
  ["8755762b8b0a0fd3aaf3d80850eb3c48", 160, 600],
].map(([key, width, height]) => {
  const options = JSON.stringify({ key, format: "js", width, height, params: {} });

  return {
    key,
    width,
    height,
    srcDoc: `<!doctype html>
<html lang="en">
  <head><meta charset="utf-8" /><title>Advertisement</title></head>
  <body style="margin: 0; overflow: hidden">
    <script>window.atOptions = ${options};</script>
    <script src="https://bauval.org/22/${key}"></script>
  </body>
</html>`,
  };
});

const wallStyle = {
  display: "flex",
  flexWrap: "wrap",
  justifyContent: "center",
  alignItems: "flex-start",
  gap: 16,
};

const frameStyle = {
  display: "block",
  flexShrink: 0,
  border: 0,
  background: "white",
  boxShadow: "0 0 0 1px #dfe8dd",
};

export default function AdWallEasterEgg() {
  const wallRef = useRef(null);
  const [wallWidth, setWallWidth] = useState(0);

  useEffect(() => {
    const wall = wallRef.current;
    const measureWidth = () => setWallWidth(wall.clientWidth);
    const observer = new ResizeObserver(measureWidth);

    measureWidth();
    observer.observe(wall);
    return () => observer.disconnect();
  }, []);

  return (
    <main className="page" style={{ paddingInline: 0 }}>
      <div className="page-heading" style={{ paddingInline: 16, textAlign: "center" }}>
        <h1>Ad wall</h1>
      </div>

      <div ref={wallRef} style={wallStyle}>
        {banners.filter(({ width }) => width <= wallWidth).map(({ key, width, height, srcDoc }) => (
          <iframe
            key={key}
            title={`${width} × ${height} banner`}
            width={width}
            height={height}
            srcDoc={srcDoc}
            loading="lazy"
            sandbox="allow-scripts allow-popups"
            style={frameStyle}
          />
        ))}
      </div>
    </main>
  );
}