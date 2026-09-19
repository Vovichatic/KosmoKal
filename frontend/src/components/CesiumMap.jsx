import { Viewer, Entity, PointGraphics, ImageryLayer } from 'resium';
import { Cartesian3, Color, UrlTemplateImageryProvider } from 'cesium';

const googleProvider = new UrlTemplateImageryProvider({
  url: 'https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
  maximumLevel: 20,
});

export default function CesiumMap() {
  const position = Cartesian3.fromDegrees(37.6173, 55.7558, 400000); 

  return (
    <div className="absolute inset-0">
      <Viewer 
        full 
        timeline={false} 
        animation={false} 
        baseLayerPicker={false} 
        geocoder={false} 
        homeButton={false} 
        navigationHelpButton={false} 
        sceneModePicker={false} 
        imageryProvider={false}
      >
        <ImageryLayer imageryProvider={googleProvider} />
        
        <Entity position={position} name="Международная космическая станция">
          <PointGraphics pixelSize={14} color={Color.RED} outlineColor={Color.WHITE} outlineWidth={2} />
        </Entity>
      </Viewer>
    </div>
  );
}
