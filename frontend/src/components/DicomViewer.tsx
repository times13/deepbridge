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
    cornerstone.loadImage(imageId).then((image) => {
      cornerstone.displayImage(el, image)
      cornerstone.fitToWindow(el)
    }).catch(console.error)
  }, [file])

  return (
    <div
      ref={elementRef}
      className="bg-black rounded-xl flex-1 w-full"
      style={{ minHeight: 480 }}
    />
  )
}