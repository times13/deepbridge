import { useEffect, useRef } from 'react'
import * as cornerstone from 'cornerstone-core'
import * as cornerstoneWADOImageLoader from 'cornerstone-wado-image-loader'
import * as dicomParser from 'dicom-parser'

cornerstoneWADOImageLoader.external.cornerstone = cornerstone
cornerstoneWADOImageLoader.external.dicomParser = dicomParser
cornerstoneWADOImageLoader.configure({ useWebWorkers: true })

interface DicomViewerProps {
  file: File | null
}

export function DicomViewer({ file }: DicomViewerProps) {
  const elementRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = elementRef.current
    if (!el) return
    cornerstone.enable(el)
    return () => { try { cornerstone.disable(el) } catch {} }
  }, [])

  useEffect(() => {
  const el = elementRef.current
  if (!el || !file) return
  const imageId = cornerstoneWADOImageLoader.wadouri.fileManager.add(file)
  cornerstone.loadImage(imageId).then((image: { windowWidth?: number; windowCenter?: number }) => {
    cornerstone.displayImage(el, image)
    
    // Fenêtrage automatique adapté au scanner
    const viewport = cornerstone.getViewport(el)
    if (viewport) {
      viewport.voi.windowWidth = image.windowWidth || 400
      viewport.voi.windowCenter = image.windowCenter || 40
      cornerstone.setViewport(el, viewport)
    }
    
    // Centrer et adapter au conteneur
    cornerstone.fitToWindow(el)
  }).catch(console.error)
}, [file])

useEffect(() => {
  function handleResize() {
    const el = elementRef.current
    if (el) {
      try {
        cornerstone.resize(el)
        cornerstone.fitToWindow(el)
      } catch {}
    }
  }
  window.addEventListener('resize', handleResize)
  return () => window.removeEventListener('resize', handleResize)
}, [])

  return (
    <div
      ref={elementRef}
      className="bg-black rounded-xl flex-1 w-full"
      style={{ minHeight: 480 }}
    />
  )
}