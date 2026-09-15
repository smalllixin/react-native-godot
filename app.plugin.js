const path = require("node:path");
const fs = require("node:fs");
const {
  IOSConfig,
  withGradleProperties,
  withDangerousMod,
  withXcodeProject,
} = require("expo/config-plugins");
const toolchainPath = path.join(__dirname, ".godot-toolchain.json");
const prebuiltFiles = [
  ...(fs.existsSync(toolchainPath)
    ? JSON.parse(fs.readFileSync(toolchainPath, "utf8")).prebuiltFiles
    : []),
  ...require("./package.json").prebuiltFiles,
];

const ANDROID_PROPERTIES = {
  "android.minSdkVersion": "29",
  "reactNativeArchitectures": "arm64-v8a",
};
const GODOT_MAVEN_PROPERTY = "android.extraMavenRepos";
const libGodotAndroid = prebuiltFiles.find(
  (entry) => entry.name === "libgodot-android"
);

if (!libGodotAndroid) {
  throw new Error("Missing libgodot-android prebuilt metadata in package.json");
}

function setGradleProperty(properties, key, value) {
  const property = properties.find(
    (entry) => entry.type === "property" && entry.key === key
  );

  if (property) {
    property.value = value;
  } else {
    properties.push({ type: "property", key, value });
  }
}

function isGodotMavenRepository(repository) {
  return (
    repository &&
    typeof repository.url === "string" &&
    /\/android\/libs\/libgodot-android\/[^/]+\/?$/.test(
      repository.url.replaceAll("\\", "/")
    )
  );
}

function addGodotMavenRepository(properties, platformProjectRoot) {
  const property = properties.find(
    (entry) => entry.type === "property" && entry.key === GODOT_MAVEN_PROPERTY
  );
  let repositories = [];

  if (property) {
    repositories = JSON.parse(property.value);
    if (!Array.isArray(repositories)) {
      throw new Error(`${GODOT_MAVEN_PROPERTY} must be a JSON array`);
    }
  }

  const repositoryPath = path
    .relative(
      path.join(platformProjectRoot, "app"),
      path.join(
        __dirname,
        "android",
        "libs",
        "libgodot-android",
        libGodotAndroid.version
      )
    )
    .split(path.sep)
    .join("/");
  repositories = repositories.filter(
    (repository) => !isGodotMavenRepository(repository)
  );
  repositories.push({ url: repositoryPath });
  setGradleProperty(
    properties,
    GODOT_MAVEN_PROPERTY,
    JSON.stringify(repositories)
  );
}

function withGodotAndroid(config) {
  config = withGradleProperties(config, (projectConfig) => {
    for (const [key, value] of Object.entries(ANDROID_PROPERTIES)) {
      setGradleProperty(projectConfig.modResults, key, value);
    }
    addGodotMavenRepository(
      projectConfig.modResults,
      projectConfig.modRequest.platformProjectRoot
    );

    return projectConfig;
  });
  return config;
}

function withGodotPacks(config, iosPacks) {
  if (!iosPacks.length) {
    return config;
  }

  return withXcodeProject(config, (projectConfig) => {
    const project = projectConfig.modResults;
    IOSConfig.XcodeUtils.ensureGroupRecursively(project, "Resources");

    for (const pack of iosPacks) {
      IOSConfig.XcodeUtils.addResourceFileToGroup({
        filepath: pack,
        groupName: "Resources",
        isBuildFile: true,
        project,
        verbose: true,
      });
    }

    return projectConfig;
  });
}

module.exports = (config, { iosPacks = [], androidPacks = [] } = {}) => {
  config = withGodotPacks(withGodotAndroid(config), iosPacks);
  if (!androidPacks.length) return config;
  return withDangerousMod(config, [
    "android",
    (mod) => {
      const destination = path.join(
        mod.modRequest.platformProjectRoot,
        "app/src/main/assets"
      );
      fs.mkdirSync(destination, { recursive: true });
      for (const pack of androidPacks) {
        const source = path.resolve(mod.modRequest.projectRoot, pack);
        if (!fs.existsSync(source))
          throw new Error(
            `Missing Godot pack ${pack}; export the fixtures first.`
          );
        fs.copyFileSync(source, path.join(destination, path.basename(pack)));
      }
      return mod;
    },
  ]);
};
