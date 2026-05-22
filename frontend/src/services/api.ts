import axios from 'axios'

const api = axios.create({
  baseURL: 'http://localhost:8000',
})

export async function checkHealth() {
  const res = await api.get('/api/health')
  return res.data
}

export async function analyzePatient(files: File[]) {
  const formData = new FormData()
  files.forEach(f => formData.append('files', f))
  const res = await api.post('/api/analyze', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
  return res.data
}

export default api