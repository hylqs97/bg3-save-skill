using System.Security.Cryptography;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using LSLib.LS;
using LSLib.LS.Enums;
using LSLib.LS.Story;

internal static class Program
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
        WriteIndented = false
    };

    private static int Main(string[] args)
    {
        try
        {
            if (args.Length == 0) throw new ArgumentException("A command is required.");
            switch (args[0])
            {
                case "story-read":
                    RequireCount(args, 2, 3);
                    Emit(Export(ReadStory(args[1])), args.Length == 3 ? args[2] : null);
                    break;
                case "story-roundtrip":
                    RequireCount(args, 3, 3);
                    Roundtrip(args[1], args[2]);
                    break;
                case "story-set-global-flag":
                case "story-unset-global-flag":
                    RequireCount(args, 4, 4);
                    EditGlobalFlag(args[1], args[2], args[3], args[0] == "story-set-global-flag");
                    break;
                case "resource-convert":
                    RequireCount(args, 3, 5);
                    if (args.Length != 3 && (args.Length != 5 || args[3] != "--template"))
                        throw new ArgumentException("resource-convert input output [--template original.lsf]");
                    RequireDistinct(args[1], args[2]);
                    ConvertResource(args[1], args[2], args.Length == 5 ? args[4] : null);
                    break;
                case "package-list":
                    RequireCount(args, 2, 2);
                    ListPackage(args[1]);
                    break;
                case "package-create":
                    RequireCount(args, 3, 6);
                    if (args.Length is not (3 or 4 or 6) || (args.Length == 6 && args[4] != "--template"))
                        throw new ArgumentException("package-create directory output [18 [--template original.lsv]]");
                    CreatePackage(args[1], args[2], args.Length >= 4 ? uint.Parse(args[3]) : 18,
                        args.Length == 6 ? args[5] : null);
                    break;
                case "fixture-story":
                    RequireCount(args, 2, 2);
                    CreateFixtureStory(args[1]);
                    break;
                default:
                    throw new ArgumentException("Unknown command. Available: story-read, story-roundtrip, story-set-global-flag, story-unset-global-flag, resource-convert, package-list, package-create, fixture-story.");
            }
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(JsonSerializer.Serialize(new { error = "lslib_bridge_error", message = error.Message, exception = error.GetType().Name }, JsonOptions));
            return 2;
        }
    }

    private static void RequireCount(string[] args, int minimum, int maximum)
    {
        if (args.Length < minimum || args.Length > maximum) throw new ArgumentException($"Wrong argument count for {args[0]}.");
    }

    private static void RequireDistinct(string input, string output)
    {
        if (Path.GetFullPath(input).Equals(Path.GetFullPath(output), OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal))
            throw new ArgumentException("Input and output must differ; in-place binary edits are prohibited.");
        if (File.Exists(output)) throw new IOException("Output already exists; refusing overwrite.");
    }

    private static Story ReadStory(string path)
    {
        using var stream = File.OpenRead(path);
        return new StoryReader().Read(stream);
    }

    private static object Export(Story story)
    {
        var databases = story.Databases.Values.OrderBy(db => db.Index).Select(db => new
        {
            Id = db.Index,
            Name = db.OwnerNode?.Name ?? "",
            Arity = db.Parameters.Types.Count,
            ParameterTypes = db.Parameters.Types.Select(id => new { Id = id, Name = TypeName(story, id), BuiltinId = Builtin(story, id) }).ToArray(),
            Facts = db.Facts.Select(fact => new
            {
                Columns = fact.Columns.Select(value => new
                {
                    TypeId = value.TypeId,
                    Type = TypeName(story, value.TypeId),
                    BuiltinId = Builtin(story, value.TypeId),
                    Value = PlainValue(story, value)
                }).ToArray()
            }).ToArray()
        }).ToArray();
        return new
        {
            SchemaVersion = 1,
            OsirisVersion = $"{story.MajorVersion}.{story.MinorVersion}",
            ShortTypeIds = story.ShortTypeIds,
            DatabaseCount = databases.Length,
            FactCount = story.Databases.Values.Sum(db => db.Facts.Count),
            Databases = databases
        };
    }

    private static string TypeName(Story story, uint id) => story.Types.TryGetValue(id, out var type) ? type.Name : $"UNKNOWN_{id}";

    private static uint Builtin(Story story, uint id)
    {
        var seen = new HashSet<uint>();
        while (story.Types.TryGetValue(id, out var type) && type.Alias != 0)
        {
            if (!seen.Add(id)) throw new InvalidDataException("Cyclic story type alias.");
            id = type.Alias;
        }
        return id;
    }

    private static object? PlainValue(Story story, Value value)
    {
        if (story.Enums.ContainsKey(value.TypeId)) return value.StringValue;
        return Builtin(story, value.TypeId) switch
        {
            0 => null,
            1 => value.IntValue,
            2 => value.Int64Value,
            3 => value.FloatValue,
            _ => value.StringValue
        };
    }

    private static string SemanticDigest(Story story)
    {
        // Export includes every database and typed fact, not only user-visible fields.
        var json = JsonSerializer.SerializeToUtf8Bytes(Export(story), JsonOptions);
        return Convert.ToHexString(SHA256.HashData(json)).ToLowerInvariant();
    }

    private static void WriteStory(Story story, string output)
    {
        using var stream = new FileStream(output, FileMode.CreateNew, FileAccess.Write);
        new StoryWriter().Write(stream, story, leaveOpen: false);
    }

    private static void Roundtrip(string input, string output)
    {
        RequireDistinct(input, output);
        var story = ReadStory(input);
        var before = SemanticDigest(story);
        WriteStory(story, output);
        var after = SemanticDigest(ReadStory(output));
        if (before != after) throw new InvalidDataException("Story roundtrip changed database schema or typed facts.");
        Emit(new { Verified = true, SemanticSha256 = after, Capability = "experimental", GameLoadValidated = false }, null);
    }

    private static void EditGlobalFlag(string input, string output, string flag, bool enabled)
    {
        RequireDistinct(input, output);
        // The persisted FLAG may have a symbolic prefix followed by a UUID.
        if (!Regex.IsMatch(flag, @"(?:^|_)[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"))
            throw new ArgumentException("Use the full persisted flag UUID or symbolic-name_UUID; labels alone are ambiguous.");
        var story = ReadStory(input);
        var candidates = story.Databases.Values.Where(db => db.OwnerNode?.Name == "DB_GlobalFlag" && db.Parameters.Types.Count == 1).ToArray();
        if (candidates.Length != 1) throw new InvalidDataException("Expected exactly one DB_GlobalFlag(1).");
        var database = candidates[0];
        var flagUuid = flag[^36..];
        var matches = database.Facts.Where(f => f.Columns.Count == 1 &&
            f.Columns[0].StringValue?.EndsWith(flagUuid, StringComparison.OrdinalIgnoreCase) == true).ToArray();
        if (matches.Length > 1) throw new InvalidDataException("Duplicate global flag rows; refusing ambiguous mutation.");
        bool changed = false;
        if (enabled && matches.Length == 0)
        {
            var typeId = database.Parameters.Types[0];
            if (Builtin(story, typeId) != 5) throw new InvalidDataException("Global flag parameter is not GUIDSTRING-compatible.");
            // StoryReader resolves aliased values to builtin IDs (FLAG -> GUIDSTRING).
            // Use the builtin for an identical exported value after writer readback.
            database.Facts.Add(new Fact { Columns = [new Value { TypeId = 5, StringValue = flag, IsValid = true, Index = -1 }] });
            changed = true;
        }
        else if (!enabled && matches.Length == 1)
        {
            database.Facts.Remove(matches[0]);
            changed = true;
        }
        var expected = SemanticDigest(story);
        WriteStory(story, output);
        if (SemanticDigest(ReadStory(output)) != expected) throw new InvalidDataException("Flag mutation did not roundtrip exactly.");
        Emit(new
        {
            Capability = "experimental",
            Changed = changed,
            Flag = flag,
            Enabled = enabled,
            Verified = true,
            GameLoadValidated = false,
            Warning = "Only the Osiris DB_GlobalFlag fact is changed. ECS flags, journal state, callbacks and downstream story consequences are not synchronized. Do not treat this as a quest repair."
        }, null);
    }

    private static void ConvertResource(string input, string output, string? template)
    {
        var resource = ResourceUtils.LoadResource(input, ResourceLoadParameters.FromGameVersion(Game.BaldursGate3));
        var conversion = ResourceConversionParameters.FromGameVersion(Game.BaldursGate3);
        string? lsfSource = template;
        if (lsfSource == null && ResourceUtils.ExtensionToResourceFormat(input) == ResourceFormat.LSF) lsfSource = input;
        if (lsfSource != null)
        {
            var source = ResourceUtils.LoadResource(lsfSource, ResourceLoadParameters.FromGameVersion(Game.BaldursGate3));
            if (ResourceUtils.ExtensionToResourceFormat(lsfSource) != ResourceFormat.LSF)
                throw new ArgumentException("The template must be an original binary LSF resource.");
            // LSLib Resource does not retain the container revision. Inspect only the
            // fixed header after LSLib has validated the entire original resource.
            using var header = new BinaryReader(File.OpenRead(lsfSource));
            if (!header.ReadBytes(4).SequenceEqual("LSOF"u8.ToArray())) throw new InvalidDataException("Invalid LSF template signature.");
            conversion.LSF = (LSFVersion)header.ReadUInt32();
            conversion.MetadataFormat = source.MetadataFormat;
            resource.Metadata = source.Metadata;
            resource.MetadataFormat = source.MetadataFormat;
        }
        ResourceUtils.SaveResource(resource, output, conversion);
        var check = ResourceUtils.LoadResource(output, ResourceLoadParameters.FromGameVersion(Game.BaldursGate3));
        Emit(new { Verified = true, Regions = check.Regions.Keys.ToArray(), MetadataFormat = check.MetadataFormat?.ToString(), LsfVersion = (uint)conversion.LSF }, null);
    }

    private static void ListPackage(string path)
    {
        using var package = new PackageReader().Read(path);
        var actualMd5 = package.Version >= PackageVersion.V15 ? ComputePackageHash(package) : null;
        var canonicalMd5 = package.Version >= PackageVersion.V15 ? ComputePackageHash(package, canonical: true) : null;
        Emit(new
        {
            Version = (uint)package.Version,
            Parts = package.Metadata.NumParts,
            HeaderMd5 = Convert.ToHexString(package.Metadata.Md5).ToLowerInvariant(),
            ComputedMd5 = actualMd5 == null ? null : Convert.ToHexString(actualMd5).ToLowerInvariant(),
            ChecksumValid = actualMd5 == null ? (bool?)null : package.Metadata.Md5.SequenceEqual(actualMd5),
            ChecksumAlgorithm = actualMd5 == null ? "unsupported" : "md5_uncompressed_physical_order_plus1",
            ComputedCanonicalMd5 = canonicalMd5 == null ? null : Convert.ToHexString(canonicalMd5).ToLowerInvariant(),
            CanonicalChecksumValid = canonicalMd5 == null ? (bool?)null : package.Metadata.Md5.SequenceEqual(canonicalMd5),
            CanonicalChecksumAlgorithm = canonicalMd5 == null ? "unsupported" : "md5_uncompressed_ordinal_ignore_case_path_order_plus1",
            PhysicalOrder = package.Files.OrderBy(file => file.ArchivePart).ThenBy(file => file.OffsetInFile).Select(file => file.Name).ToArray(),
            Flags = (byte)package.Metadata.Flags,
            Priority = package.Metadata.Priority,
            Entries = package.Files.Select(file => new { Name = file.Name, Size = file.Size(), Deleted = file.IsDeletion(), Crc = file.Crc,
                Flags = (byte)file.Flags, ArchivePart = file.ArchivePart, OffsetInFile = file.OffsetInFile }).ToArray()
        }, null);
    }

    private static byte[] ComputePackageHash(Package package, bool canonical = false)
    {
        // Native save file tables are not in physical content order. BG3's v18
        // hash follows the write order, so sorting by table order is incorrect.
        // This matches LSLib PackageWriter's Build.Files order for generated data.
        using var md5 = IncrementalHash.CreateHash(HashAlgorithmName.MD5);
        var buffer = new byte[1024 * 1024];
        var ordered = canonical ? package.Files.OrderBy(file => file.Name, StringComparer.OrdinalIgnoreCase)
            : package.Files.OrderBy(file => file.ArchivePart).ThenBy(file => file.OffsetInFile);
        foreach (var file in ordered)
        {
            if (file.IsDeletion()) throw new InvalidDataException("Deletion entries cannot be verified as a savegame.");
            using var contents = file.CreateContentReader();
            int read;
            while ((read = contents.Read(buffer, 0, buffer.Length)) != 0) md5.AppendData(buffer, 0, read);
        }
        var digest = md5.GetHashAndReset();
        for (var index = 0; index < digest.Length; index++) digest[index] = (byte)((digest[index] + 1) & 0xff);
        return digest;
    }

    private static void CreatePackage(string directory, string output, uint version, string? template)
    {
        if (File.Exists(output)) throw new IOException("Output already exists; refusing overwrite.");
        if (version != 18) throw new ArgumentException("Only current BG3 LSPK v18 is supported for repacking; other versions are read-only.");
        if (!Directory.Exists(directory)) throw new DirectoryNotFoundException(directory);
        var inputFiles = CollectPackageInputs(directory);
        var build = new PackageBuildData
        {
            Version = (PackageVersion)version,
            // Divine selects zlib for .lsv; current native saves may use zstd.
            // Both use the same unpacked-content integrity checksum.
            Compression = CompressionMethod.Zlib,
            CompressionLevel = LSCompressionLevel.Default,
            Hash = true
        };
        if (template == null)
        {
            // A native save hashes all normalized paths together, including nested
            // LevelCache members. Packager's separate files/subdirectories traversal
            // changes that order and is unsuitable even for an unchanged repack.
            build.Files = inputFiles
                .Select(path => PackageBuildInputFile.CreateFromFilesystem(path, Path.GetRelativePath(directory, path).Replace('\\', '/')))
                .OrderBy(file => file.Path, StringComparer.OrdinalIgnoreCase).ToList();
            using var writer = PackageWriterFactory.Create(build, output);
            writer.Write();
        }
        else
        {
            using var original = new PackageReader().Read(template);
            if (original.Version != PackageVersion.V18 || original.Metadata.NumParts != 1 || original.Files.Any(file => file.IsDeletion()))
                throw new InvalidDataException("Only a complete single-part v18 save can be a package template.");
            if ((byte)original.Metadata.Flags != 0 || original.Metadata.Priority != 0)
                throw new InvalidDataException("Only the verified native save package flags=0 and priority=0 layout can be a template.");
            var physical = original.Files.OrderBy(file => file.ArchivePart).ThenBy(file => file.OffsetInFile).ToList();
            if (!ComputePackageHash(original).SequenceEqual(original.Metadata.Md5) ||
                !ComputePackageHash(original, canonical: true).SequenceEqual(original.Metadata.Md5))
                throw new InvalidDataException("Template hash must match both original physical order and native canonical path order.");
            var members = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var file in physical)
            {
                if (file.Name.Contains('\\') || Path.IsPathRooted(file.Name) || file.Name.Contains(':') ||
                    file.Name.Split('/').Any(part => part.Length == 0 || part is "." or "..") || !members.Add(file.Name))
                    throw new InvalidDataException("Unsafe or duplicate template member path.");
                var path = Path.Combine(directory, file.Name.Replace('/', Path.DirectorySeparatorChar));
                if (!File.Exists(path) || (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("Missing template member or unsafe symbolic link.");
                build.Files.Add(PackageBuildInputFile.CreateFromFilesystem(path, file.Name));
            }
            var extractedMembers = inputFiles
                .Select(path => Path.GetRelativePath(directory, path).Replace('\\', '/')).ToHashSet(StringComparer.OrdinalIgnoreCase);
            if (!members.SetEquals(extractedMembers)) throw new InvalidDataException("Template and extracted member sets differ.");
            build.Flags = original.Metadata.Flags;
            build.Priority = original.Metadata.Priority;
            using var writer = new TemplatePackageWriter(build, output, physical, original.Files);
            writer.Write();
        }
        ListPackage(output);
    }

    private static List<string> CollectPackageInputs(string directory)
    {
        var pending = new Stack<string>();
        pending.Push(Path.GetFullPath(directory));
        var files = new List<string>();
        while (pending.TryPop(out var current))
        {
            if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Package input directories must not be symbolic links or junctions.");
            foreach (var path in Directory.EnumerateFileSystemEntries(current))
            {
                var attributes = File.GetAttributes(path);
                if ((attributes & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("Package inputs must not contain symbolic links or junctions.");
                if ((attributes & FileAttributes.Directory) != 0) pending.Push(path);
                else files.Add(path);
            }
        }
        return files;
    }

    // The upstream writer couples file-table order to payload order. Native BG3
    // uses a separate table order. This adapter changes orchestration only; all
    // compression, padding, checksum, header and table serializers remain LSLib's.
    // The sole internal table method is pinned to the checked LSLib 1.20.4 API.
    private sealed class TemplatePackageWriter(PackageBuildData build, string output,
        List<PackagedFileInfo> physical, List<PackagedFileInfo> table) : PackageWriter(build, output)
    {
        public override void Write()
        {
            using var writer = new BinaryWriter(MainStream, new System.Text.UTF8Encoding(false), leaveOpen: true);
            writer.Write(PackageHeaderCommon.Signature);
            WriteHeader(writer);
            var written = new Dictionary<string, PackageBuildTransientFile>(StringComparer.OrdinalIgnoreCase);
            for (var index = 0; index < Build.Files.Count; index++)
            {
                var flags = (byte)physical[index].Flags;
                if ((flags & 0x0f) > 3 || (flags & 0xf0) > 0x40 || (flags & 0xf0) == 0x30)
                    throw new InvalidDataException("Unsupported compression flags in template.");
                Build.Compression = (CompressionMethod)(flags & 0x0f);
                Build.CompressionLevel = (flags & 0xf0) switch
                {
                    0x10 => LSCompressionLevel.Fast,
                    0x20 => LSCompressionLevel.Default,
                    0x40 => LSCompressionLevel.Max,
                    0 => LSCompressionLevel.Default,
                    _ => throw new InvalidDataException("Unknown compression level in template.")
                };
                var entry = WriteFile(Build.Files[index]);
                // For uncompressed members, the native flags can omit the level.
                entry.Flags = physical[index].Flags;
                written.Add(entry.Name, entry);
            }
            Metadata.FileListOffset = (ulong)MainStream.Position;
            var tableWriter = typeof(PackageWriter).GetMethod("WriteCompressedFileList", BindingFlags.NonPublic | BindingFlags.Instance)
                ?? throw new MissingMethodException("Pinned LSLib compressed file-list serializer is unavailable.");
            var fileEntryType = typeof(Package).Assembly.GetType("LSLib.LS.FileEntry18")
                ?? throw new MissingMemberException("Pinned LSLib v18 file-entry type is unavailable.");
            tableWriter.MakeGenericMethod(fileEntryType).Invoke(this, [writer, table.Select(file => written[file.Name]).ToList()]);
            Metadata.FileListSize = checked((uint)(MainStream.Position - (long)Metadata.FileListOffset));
            Metadata.Md5 = ComputeArchiveHash();
            Metadata.NumParts = (uint)Streams.Count;
            MainStream.Seek(4, SeekOrigin.Begin);
            WriteHeader(writer);
        }

        private void WriteHeader(BinaryWriter writer)
        {
            var headerType = typeof(Package).Assembly.GetType("LSLib.LS.LSPKHeader16")
                ?? throw new MissingMemberException("Pinned LSLib v18 header type is unavailable.");
            var factory = headerType.GetMethod("FromCommonHeader", BindingFlags.Static | BindingFlags.Public)
                ?? throw new MissingMethodException("Pinned LSLib header serializer is unavailable.");
            var header = factory.Invoke(null, [Metadata]);
            var serializer = typeof(BinUtils).GetMethod("WriteStruct", BindingFlags.Public | BindingFlags.Static)
                ?? throw new MissingMethodException("Pinned LSLib structure serializer is unavailable.");
            serializer.MakeGenericMethod(headerType).Invoke(null, [writer, header]);
        }
    }

    private static void CreateFixtureStory(string output)
    {
        if (File.Exists(output)) throw new IOException("Output already exists; refusing overwrite.");
        // Entirely invented Osiris data: no player data or copyrighted story script.
        var story = new Story
        {
            MajorVersion = 1, MinorVersion = 15, ShortTypeIds = true,
            Types = new(), Enums = new(), Nodes = new(), Adapters = new(), Databases = new(),
            Goals = new(), DivObjects = new(), Functions = new(), GlobalActions = new(),
            ExternalStringTable = new(), FunctionSignatureMap = new()
        };
        foreach (var type in new[] { (0u, "UNKNOWN"), (1u, "INTEGER"), (2u, "INTEGER64"), (3u, "REAL"), (4u, "STRING"), (5u, "GUIDSTRING") })
            story.Types.Add(type.Item1, OsirisType.MakeBuiltin((byte)type.Item1, type.Item2));
        story.Types.Add(6, new OsirisType { Index = 6, Alias = 5, Name = "FLAG", IsBuiltin = false });
        var database = new Database { Index = 1, Parameters = new ParameterList { Types = [6] } };
        var node = new DatabaseNode { Index = 1, Name = "DB_GlobalFlag", NumParams = 1, DatabaseRef = new DatabaseReference(story, 1), ReferencedBy = [] };
        database.OwnerNode = node;
        database.Facts = new FactCollection(database, story)
        {
            new Fact { Columns = [new Value { TypeId = 5, StringValue = "BG3SAVE_SyntheticFlag_00000000-0000-0000-0000-000000000001", IsValid = true, Index = -1 }] }
        };
        story.Databases.Add(1, database);
        story.Nodes.Add(1, node);
        // An invented definition catalog retains the flag identity after a test
        // unsets the active global fact; it must never be interpreted as active.
        var catalog = new Database { Index = 2, Parameters = new ParameterList { Types = [6] } };
        var catalogNode = new DatabaseNode { Index = 2, Name = "DB_BG3SAVE_FlagCatalog", NumParams = 1, DatabaseRef = new DatabaseReference(story, 2), ReferencedBy = [] };
        catalog.OwnerNode = catalogNode;
        catalog.Facts = new FactCollection(catalog, story)
        {
            new Fact { Columns = [new Value { TypeId = 5, StringValue = "BG3SAVE_SyntheticFlag_00000000-0000-0000-0000-000000000001", IsValid = true, Index = -1 }] }
        };
        story.Databases.Add(2, catalog);
        story.Nodes.Add(2, catalogNode);
        WriteStory(story, output);
        Emit(Export(ReadStory(output)), null);
    }

    private static void Emit(object value, string? output)
    {
        var text = JsonSerializer.Serialize(value, JsonOptions);
        if (output == null) Console.WriteLine(text);
        else File.WriteAllText(output, text + "\n", new System.Text.UTF8Encoding(false));
    }
}
