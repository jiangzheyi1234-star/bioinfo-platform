import { reactive } from 'vue';

export const bridgeStore = reactive({
  bridge: null,
  ready: false,
  host: 'browser',
  connectedAt: '',
  methods: [],
  lastRunResult: '',
  lastExecutionUpdate: '',
  lastRunPayload: null,
  lastExecutionPayload: null,
  lastRunAt: '',
  lastExecutionAt: '',
  error: '',
});
