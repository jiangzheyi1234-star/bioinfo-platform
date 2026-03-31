import { reactive } from 'vue';

export const workbenchStore = reactive({
  title: '结果工作台',
  subtitle: '',
  projectId: '',
  features: [],
  views: {},
  selectedFeatureId: '',
  executionViews: {},
  loading: false,
  error: '',
});
