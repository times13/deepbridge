import axios from 'axios'

const api = axios.create({
  baseURL: 'http://localhost:8000',
})

export async function getPatients() {
  const res = await api.get('/api/patients')
  return res.data
}

export async function analyzePatient(patientId: string) {
  const res = await api.post(`/api/patients/${patientId}/analyze`)
  return res.data
}

export default api