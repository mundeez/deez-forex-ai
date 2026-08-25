import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

const config = [
  ...nextCoreWebVitals,
  {
    rules: {
      // Preserve existing baseline; next/core-web-vitals sets the rest.
    },
  },
];

export default config;
