#!/usr/bin/perl
# Protocol reference harness: runs FHEM's own THZ_Set / THZ_Parse1 from
# docs/legacy/00_THZ.pm against a simulated heat pump.
#
# Only the *protocol* is taken from FHEM: telegram framing, checksum,
# escaping, the read-modify-write of 2.x blocks, and how each value type is
# encoded and decoded. The parameter definitions (block, position, length,
# type, factor, limits) are passed in from the integration's own register
# maps, which are more current than the tables in the FHEM module; FHEM's
# built-in tables are only used for the value types themselves.
#
# FHEM's runtime (logging, readings, serial I/O) is stubbed and delays
# (select(undef, undef, undef, x)) are removed so the run is fast.
#
# Input (JSON on stdin):
#   {"module": path, "firmware": "2.06",
#    "sets": {name: {parent|cmd2, argMin, argMax, type}},   added to %sets
#    "gets": {name: {cmd2, type}},                          added to %gets
#    "parsing": {type: [[title, pos, len, type, factor], ...]},
#    "blocks": {"17": "<hex data after the address byte>", ...},
#    "cases": [["p01RoomTempDay", "21"], ...],
#    "parse": {"17": "<parsing type to decode block 17 with>", ...},
#    "decode": ["<raw answer hex>", ...]}
# Output (JSON on stdout):
#   {"sets": {"<param> <value>": {"telegrams": [hex, ...]} | {"error": msg}},
#    "parsed": {"<block>": "<THZ_Parse1 output>"},
#    "decoded": {"<raw answer hex>": "<THZ_decode error>" | null}}
use strict;
use warnings;
use JSON::PP;

BEGIN {
    # FHEM helper modules the THZ module "use"s; not needed here.
    $INC{"$_.pm"} = 1 for qw(SetExtensions Blocking DevIo);
}

package main;

# FHEM globals the module refers to (normally provided by fhem.pl).
our (%defs, %attr, %data, %selectlist, %intAt, $init_done, $reread_active,
     $readingFnAttributes);
$init_done = 0;

sub Log3 { }
sub readingsSingleUpdate { }
sub AttrVal { my ($name, $attr_name, $default) = @_;
    return defined $attr{$name}{$attr_name} ? $attr{$name}{$attr_name} : $default; }
sub ReadingsVal { return $_[2]; }

my $input = decode_json(do { local $/; <STDIN> });

my $src = do {
    open my $fh, "<", $input->{module} or die "cannot read module: $!";
    local $/; <$fh>;
};
$src =~ s/select\(undef,\s*undef,\s*undef,\s*[^)]*\)/1/g;
# Appended to the module source so they can reach its file-scoped (my)
# %sets / %gets / %parsinghash tables.
$src .= <<'OVERRIDES';

sub THZ_TestOverride {
    my ($sets, $gets, $parsing) = @_;
    %parsinghash = (%parsinghash, %$parsing);
    %sets = (%sets, %$sets);
    %gets = (%gets, %$gets, %$sets);
}

sub THZ_TestParse {
    my ($hash, $message, $type) = @_;
    my %saved = %gets;
    %gets = (test_block => { cmd2 => substr($message, 2, 2), type => $type });
    my $parsed = THZ_Parse1($hash, $message);
    %gets = %saved;
    return $parsed;
}
1;
OVERRIDES
{
    local $SIG{__WARN__} = sub { };
    eval $src;
    die "loading THZ module failed: $@" if $@;
}

my %blocks = map { uc($_) => uc($input->{blocks}{$_}) }
    keys %{ $input->{blocks} || {} };
my @sent;

sub unescape_hex {
    my ($hex) = @_;
    $hex = THZ_replacebytes($hex, "1010", "10");
    return THZ_replacebytes($hex, "2B18", "2B");
}

{
    no warnings qw(redefine once);
    *main::THZ_AvoidCollisions = sub ($) { };
    *main::THZ_Get = sub ($@) { return ""; };
    *main::THZ_Get_Comunication = sub ($$) {
        my ($hash, $telegram) = @_;
        my $body = unescape_hex(substr($telegram, 4, length($telegram) - 8));
        my $payload = substr($body, 2);    # drop checksum
        if (substr($telegram, 0, 4) eq "0180") {
            push @sent, $telegram;
            return (undef, "");
        }
        my $addr = substr($payload, 0, 2);
        die "unknown block $addr" unless defined $blocks{$addr};
        my $data = $addr . $blocks{$addr};
        my $crc = THZ_checksum("0100XX" . $data . "1003");
        return (undef, $crc . $data);
    };
}

my $name = "thz";
my $hash = { NAME => $name, STATE => "opened", DeviceName => "none" };
$defs{$name} = $hash;
$attr{$name}{firmware} = $input->{firmware};
THZ_Attr("set", $name, "firmware", $input->{firmware});
THZ_TestOverride(
    $input->{sets} || {}, $input->{gets} || {}, $input->{parsing} || {}
);

my %result;
for my $case (@{ $input->{cases} || [] }) {
    my ($param, $value) = @$case;
    @sent = ();
    my $ret = eval { THZ_Set($hash, $name, $param, $value) };
    my $key = "$param $value";
    if ($@) {
        $result{$key} = { error => "$@" };
    } elsif (!@sent) {
        $result{$key} = { error => "no SET sent: " . ($ret // "") };
    } else {
        $result{$key} = { telegrams => [@sent] };
    }
}

my %parsed;
for my $addr (keys %{ $input->{parse} || {} }) {
    my $data = uc($addr) . $blocks{uc($addr)};
    my $crc = THZ_checksum("0100XX" . $data . "1003");
    $parsed{$addr} = THZ_TestParse($hash, $crc . $data, $input->{parse}{$addr});
}
my %decoded;
for my $answer (@{ $input->{decode} || [] }) {
    my ($err) = THZ_decode(uc($answer));
    $decoded{$answer} = $err;
}
print encode_json({ sets => \%result, parsed => \%parsed, decoded => \%decoded });
