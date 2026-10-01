// Frontend package is the existing product-version authority.
const metadata = require('./package.json');
module.exports = {
  ...metadata.build,
  extraMetadata: { version: require('../frontend/package.json').version },
};
