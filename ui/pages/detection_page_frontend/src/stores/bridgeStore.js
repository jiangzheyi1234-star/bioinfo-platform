import { reactive } from 'vue';

export const bridgeStore = reactive({
  bridge: null,
  ready: false,
  host: 'browser',
  methods: [],
  lastRunResult: '',
  lastExecutionUpdate: '',
  lastRunPayload: null,
  lastExecutionPayload: null,
  error: '',
});
