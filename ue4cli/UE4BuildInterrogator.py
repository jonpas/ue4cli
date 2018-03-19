from .ThirdPartyLibraryDetails import ThirdPartyLibraryDetails
from .UnrealManagerException import UnrealManagerException
from .CachedDataManager import CachedDataManager
from .Utility import Utility
import json, os, platform, shutil, tempfile

class UE4BuildInterrogator(object):
	
	def __init__(self, engineRoot, engineVersionHash, runUBTFunc):
		self.engineRoot = engineRoot
		self.engineSourceDir = 'Engine/Source/'
		self.engineVersionHash = engineVersionHash
		self.runUBTFunc = runUBTFunc
	
	def list(self, platformIdentifier, configuration):
		"""
		Returns the list of supported UE4-bundled third-party libraries
		"""
		modules = self._getThirdPartyLibs(platformIdentifier, configuration)
		return sorted([m['Name'] for m in modules])
	
	def interrogate(self, platformIdentifier, configuration, libraries, libOverrides = {}):
		"""
		Interrogates UnrealBuildTool about the build flags for the specified third-party libraries
		"""
		
		# Determine which libraries need their modules parsed by UBT, and which are override-only
		libModules = list([lib for lib in libraries if lib not in libOverrides])
		
		# Check that we have at least one module to parse
		details = ThirdPartyLibraryDetails()
		if len(libModules) > 0:
			
			# Retrieve the list of third-party library modules from UnrealBuildTool
			modules = self._getThirdPartyLibs(platformIdentifier, configuration)
			
			# Filter the list of modules to include only those that were requested
			modules = [m for m in modules if m['Name'] in libModules]
			
			# Emit a warning if any of the requested modules are not supported
			names = [m['Name'] for m in modules]
			unsupported = ['"' + m + '"' for m in libModules if m not in names]
			if len(unsupported) > 0:
				Utility.printStderr('Warning: unsupported libraries ' + ','.join(unsupported))
			
			# Some libraries are listed as just the filename without the leading directory (especially prevalent under Windows)
			for module in modules:
				if len(module['PublicAdditionalLibraries']) > 0 and len(module['PublicLibraryPaths']) > 0:
					libPath = (self._absolutePaths(module['PublicLibraryPaths']))[0]
					libs = list([lib.replace('\\', '/') for lib in module['PublicAdditionalLibraries']])
					libs = list([os.path.join(libPath, lib) if '/' not in lib else lib for lib in libs])
					module['PublicAdditionalLibraries'] = libs
			
			# Flatten the lists of paths
			fields = [
				'Directory',
				'PublicAdditionalLibraries',
				'PublicLibraryPaths',
				'PublicSystemIncludePaths',
				'PublicIncludePaths',
				'PrivateIncludePaths',
				'PublicDefinitions'
			]
			flattened = {}
			for field in fields:
				transform = (lambda l: self._absolutePaths(l)) if field != 'Definitions' else None
				flattened[field] = self._flatten(field, modules, transform)
			
			# Compose the prefix directories from the module root directories, the header and library paths, and their direct parent directories
			libraryDirectories = flattened['PublicLibraryPaths']
			headerDirectories  = flattened['PublicSystemIncludePaths'] + flattened['PublicIncludePaths'] + flattened['PrivateIncludePaths']
			modulePaths        = flattened['Directory']
			prefixDirectories  = list(set(flattened['Directory'] + headerDirectories + libraryDirectories + [os.path.dirname(p) for p in headerDirectories + libraryDirectories]))
			
			# Wrap the results in a ThirdPartyLibraryDetails instance, converting any relative directory paths into absolute ones
			details = ThirdPartyLibraryDetails(
				prefixDirs  = prefixDirectories,
				includeDirs = headerDirectories,
				linkDirs    = libraryDirectories,
				definitions = flattened['PublicDefinitions'],
				libs        = flattened['PublicAdditionalLibraries']
			)
		
		# Apply any overrides
		overridesToApply = list([libOverrides[lib] for lib in libraries if lib in libOverrides])
		for override in overridesToApply:
			details.merge(override)
		
		return details
	
	
	# "Private" methods
	
	def _absolutePaths(self, paths):
		"""
		Converts the supplied list of paths to absolute pathnames (except for pure filenames without leading relative directories)
		"""
		slashes = [p.replace('\\', '/') for p in paths]
		stripped = [p.replace('../', '') if p.startswith('../') else p for p in slashes]
		return list([p if (os.path.isabs(p) or '/' not in p) else os.path.join(self.engineRoot, self.engineSourceDir, p) for p in stripped])
	
	def _flatten(self, field, items, transform = None):
		"""
		Extracts the entry `field` from each item in the supplied iterable, flattening any nested lists
		"""
		
		# Retrieve the value for each item in the iterable
		values = [item[field] for item in items]
		
		# Flatten any nested lists
		flattened = []
		for value in values:
			flattened.extend([value] if isinstance(value, str) else value)
		
		# Apply any supplied transformation function
		return transform(flattened) if transform != None else flattened
	
	def _getThirdPartyLibs(self, platformIdentifier, configuration):
		"""
		Runs UnrealBuildTool in JSON export mode and extracts the list of third-party libraries
		"""
		
		# If we have previously cached the library list for the current engine version, use the cached data
		cachedList = CachedDataManager.getCachedDataKey(self.engineVersionHash, 'ThirdPartyLibraries')
		if cachedList != None:
			return cachedList
		
		# Create a temp directory to hold the JSON file
		tempDir = tempfile.mkdtemp()
		jsonFile = os.path.join(tempDir, 'ubt_output.json')
		
		# Invoke UnrealBuildTool in JSON export mode (make sure we specify gathering mode, since this is a prerequisite of JSON export)
		target = 'UE4Editor' if platform.system() == 'Linux' else 'UE4Game'
		self.runUBTFunc(target, platformIdentifier, configuration, ['-gather', '-jsonexport=' + jsonFile, '-SkipBuild'])
		
		# Parse the JSON output
		result = json.loads(Utility.readFile(jsonFile))
		
		# Extract the list of third-party library modules
		modules = [result['Modules'][key] for key in result['Modules']]
		thirdparty = list([m for m in modules if m['Type'] == 'EngineThirdParty'])
		
		# Remove the temp directory
		try:
			shutil.rmtree(tempDir)
		except:
			pass
		
		# Cache the list of libraries for use by subsequent runs
		CachedDataManager.setCachedDataKey(self.engineVersionHash, 'ThirdPartyLibraries', thirdparty)
		
		return thirdparty